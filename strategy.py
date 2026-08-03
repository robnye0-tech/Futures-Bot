"""
Momentum/volume scale-in-out strategy for MNQ + MES, built for a Tradeify
(Tradovate) funded futures account.

STATUS: Structurally complete, NOT yet connected to a live broker.
Requires Tradovate API credentials in .env before it can run against a
demo or funded account (see .env.example).

Risk constants in config.py (RISK_PER_TRADE_USD, DAILY_KILL_SWITCH_USD) are
conservative placeholders pending confirmation of Tradeify's exact max
trailing drawdown figure. Do not go live without verifying these against
the real account rules.
"""

from datetime import time as dtime

from dotenv import load_dotenv
from lumibot.entities import Asset
from lumibot.strategies import Strategy

import shared_state
from config import (
    ADD_INCREMENT,
    BASE_SIZE,
    DAILY_KILL_SWITCH_USD,
    FAST_EMA,
    MAX_SIZE,
    NEWS_REFRESH_MINUTES,
    SCALE_IN_ATR_MULT,
    SESSION_END_HOUR,
    SESSION_END_MIN,
    SESSION_START_HOUR,
    SESSION_START_MIN,
    SLOW_EMA,
    STOP_ATR_MULT,
    SYMBOLS,
    TARGET_1_ATR_MULT,
    TARGET_2_ATR_MULT,
    ATR_PERIOD,
    VOLUME_LOOKBACK,
    VOLUME_MULTIPLIER,
)
from news_feed import fetch_relevant_news

load_dotenv()

SESSION_START = dtime(SESSION_START_HOUR, SESSION_START_MIN)
SESSION_END = dtime(SESSION_END_HOUR, SESSION_END_MIN)


class MomentumVolumeScaler(Strategy):
    def initialize(self):
        self.sleeptime = "1M"
        self.assets = {s: Asset(s, asset_type=Asset.AssetType.CONT_FUTURE) for s in SYMBOLS}
        self.state = {s: self._fresh_state() for s in SYMBOLS}
        self.trading_day = None
        self.daily_start_equity = None
        self.daily_halted = False
        self.last_news_fetch = None
        self._refresh_news()

    def _fresh_state(self):
        return {
            "direction": None,
            "size": 0,
            "stop_price": None,
            "target_1_hit": False,
            "target_2_hit": False,
            "last_scale_price": None,
        }

    # -----------------------------------------------------------------
    # Daily reset + kill switch
    # -----------------------------------------------------------------
    def _check_new_day(self):
        dt = self.get_datetime()
        if self.trading_day != dt.date():
            self.trading_day = dt.date()
            self.daily_start_equity = self.portfolio_value
            self.daily_halted = False
            for s in SYMBOLS:
                self.state[s] = self._fresh_state()
            self.log_message(f"New trading day {self.trading_day}, start equity {self.daily_start_equity:.2f}")
        self._sync_dashboard_state()

    def _daily_pnl(self):
        return self.portfolio_value - self.daily_start_equity

    def _in_session(self):
        t = self.get_datetime().time()
        return SESSION_START <= t <= SESSION_END

    def _sync_dashboard_state(self):
        shared_state.update_state(
            trading_day=str(self.trading_day),
            daily_start_equity=self.daily_start_equity,
            portfolio_value=self.portfolio_value,
            daily_pnl=self._daily_pnl() if self.daily_start_equity else None,
            daily_halted=self.daily_halted,
        )
        shared_state.set_positions(self.state)

    def _log_trade(self, symbol, action, qty, price, reason=""):
        self.log_message(f"[{symbol}] {action} x{qty} @ {price:.2f} {reason}".strip())
        shared_state.append_trade_log({
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "price": round(price, 2),
            "reason": reason,
        })

    # -----------------------------------------------------------------
    # News refresh (rate-limit friendly - only every NEWS_REFRESH_MINUTES)
    # -----------------------------------------------------------------
    def _refresh_news(self):
        now = self.get_datetime()
        if self.last_news_fetch is not None:
            elapsed_minutes = (now - self.last_news_fetch).total_seconds() / 60
            if elapsed_minutes < NEWS_REFRESH_MINUTES:
                return
        headlines = fetch_relevant_news()
        if headlines:
            shared_state.set_news(headlines)
        self.last_news_fetch = now

    # -----------------------------------------------------------------
    # Indicators
    # -----------------------------------------------------------------
    def _compute_indicators(self, symbol):
        asset = self.assets[symbol]
        bars = self.get_historical_prices(asset, SLOW_EMA + ATR_PERIOD + VOLUME_LOOKBACK + 5, "minute")
        if bars is None or bars.df is None or len(bars.df) < SLOW_EMA + ATR_PERIOD:
            return None

        df = bars.df.copy()
        df["ema_fast"] = df["close"].ewm(span=FAST_EMA, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=SLOW_EMA, adjust=False).mean()

        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        true_range = high_low.combine(high_close, max).combine(low_close, max)
        df["atr"] = true_range.rolling(ATR_PERIOD).mean()

        df["avg_volume"] = df["volume"].rolling(VOLUME_LOOKBACK).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        return {
            "close": last["close"],
            "atr": last["atr"],
            "volume_confirmed": last["volume"] > (last["avg_volume"] * VOLUME_MULTIPLIER),
            "cross_up": prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"],
            "cross_down": prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"],
        }

    # -----------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------
    def on_trading_iteration(self):
        self._check_new_day()
        self._refresh_news()

        if self._daily_pnl() <= -DAILY_KILL_SWITCH_USD:
            if not self.daily_halted:
                self.log_message(f"DAILY KILL SWITCH HIT ({self._daily_pnl():.2f}). Flattening and halting for the day.")
                self._flatten_all()
                self.daily_halted = True
                self._sync_dashboard_state()
            return

        if not self._in_session():
            return

        for symbol in SYMBOLS:
            self._process_symbol(symbol)

        self._sync_dashboard_state()

    def _process_symbol(self, symbol):
        ind = self._compute_indicators(symbol)
        if ind is None or ind["atr"] is None or ind["atr"] <= 0:
            return

        state = self.state[symbol]
        asset = self.assets[symbol]
        price = ind["close"]

        if state["direction"] is not None:
            self._manage_open_position(symbol, asset, ind, state, price)
            return

        if ind["cross_up"] and ind["volume_confirmed"]:
            self._enter(symbol, asset, "long", price, ind["atr"])
        elif ind["cross_down"] and ind["volume_confirmed"]:
            self._enter(symbol, asset, "short", price, ind["atr"])

    def _enter(self, symbol, asset, direction, price, atr):
        state = self.state[symbol]
        side = "buy" if direction == "long" else "sell"
        order = self.create_order(asset, BASE_SIZE, side)
        self.submit_order(order)

        stop_distance = atr * STOP_ATR_MULT
        state["direction"] = direction
        state["size"] = BASE_SIZE
        state["stop_price"] = price - stop_distance if direction == "long" else price + stop_distance
        state["last_scale_price"] = price
        state["target_1_hit"] = False
        state["target_2_hit"] = False

        self._log_trade(symbol, f"ENTER {direction.upper()}", BASE_SIZE, price,
                         reason=f"stop {state['stop_price']:.2f}")

    def _manage_open_position(self, symbol, asset, ind, state, price):
        direction = state["direction"]
        atr = ind["atr"]
        favorable_move = (price - state["last_scale_price"]) if direction == "long" else (state["last_scale_price"] - price)

        stop_hit = (direction == "long" and price <= state["stop_price"]) or \
                   (direction == "short" and price >= state["stop_price"])
        if stop_hit:
            self._close_symbol(symbol, asset, state, reason="stop")
            return

        if state["size"] < MAX_SIZE and favorable_move >= (atr * SCALE_IN_ATR_MULT) and ind["volume_confirmed"]:
            add_qty = min(ADD_INCREMENT, MAX_SIZE - state["size"])
            side = "buy" if direction == "long" else "sell"
            self.submit_order(self.create_order(asset, add_qty, side))
            state["size"] += add_qty
            state["last_scale_price"] = price
            state["stop_price"] = price - atr if direction == "long" else price + atr
            self._log_trade(symbol, "SCALE IN", add_qty, price, reason=f"total {state['size']}")
            return

        entry_reference = state["last_scale_price"]
        target_1 = entry_reference + (atr * TARGET_1_ATR_MULT) if direction == "long" else entry_reference - (atr * TARGET_1_ATR_MULT)
        target_2 = entry_reference + (atr * TARGET_2_ATR_MULT) if direction == "long" else entry_reference - (atr * TARGET_2_ATR_MULT)

        hit_t1 = (direction == "long" and price >= target_1) or (direction == "short" and price <= target_1)
        hit_t2 = (direction == "long" and price >= target_2) or (direction == "short" and price <= target_2)

        if hit_t2 and not state["target_2_hit"] and state["size"] > 1:
            trim_qty = max(1, state["size"] // 3)
            self._trim(symbol, asset, state, trim_qty, direction, price)
            state["target_2_hit"] = True
            state["stop_price"] = entry_reference
        elif hit_t1 and not state["target_1_hit"] and state["size"] > 1:
            trim_qty = max(1, state["size"] // 3)
            self._trim(symbol, asset, state, trim_qty, direction, price)
            state["target_1_hit"] = True

    def _trim(self, symbol, asset, state, qty, direction, price):
        side = "sell" if direction == "long" else "buy"
        self.submit_order(self.create_order(asset, qty, side))
        state["size"] -= qty
        self._log_trade(symbol, "SCALE OUT", qty, price, reason=f"remaining {state['size']}")
        if state["size"] <= 0:
            self.state[symbol] = self._fresh_state()

    def _close_symbol(self, symbol, asset, state, reason=""):
        if state["size"] <= 0:
            return
        side = "sell" if state["direction"] == "long" else "buy"
        price_asset = self.get_last_price(asset)
        self.submit_order(self.create_order(asset, state["size"], side))
        self._log_trade(symbol, "CLOSE", state["size"], price_asset or 0.0, reason=reason)
        self.state[symbol] = self._fresh_state()

    def _flatten_all(self):
        for symbol in SYMBOLS:
            state = self.state[symbol]
            if state["size"] > 0:
                self._close_symbol(symbol, self.assets[symbol], state, reason="daily kill switch")


if __name__ == "__main__":
    # Requires TRADOVATE_* credentials in .env (see .env.example).
    # run_live() auto-detects the broker from environment variables.
    strategy = MomentumVolumeScaler()
    strategy.run_live()
