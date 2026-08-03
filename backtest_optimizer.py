"""
Walk-forward parameter robustness search for the futures scale-in-out
strategy. Supports three entry-signal families:

  - "crossover": EMA crossover + volume/trend/VWAP filters. Tested and
    found to have NO real out-of-sample edge on MNQ/MES 30m/60m - kept
    here for reference/comparison, not recommended as the active strategy.
  - "orb": Opening Range Breakout + VWAP confluence + volume + ADX
    momentum/trend-strength filter. Tested on MNQ/MES 1m/5m/15m - failed
    out-of-sample everywhere except a single MNQ 1-minute config, and that
    one only "held up" on a 3-day/26-trade out-of-sample slice (Yahoo's
    7-day cap for 1m data) - too thin to trust, and a larger TradingView
    sample on the same idea (ADX filter off) came back clearly negative
    (PF 0.83, ~258 trades). Kept for reference, not recommended.
  - "meanrev": VWAP mean-reversion - fades price back toward VWAP when
    stretched (2x ATR band) AND the market is range-bound (ADX below a
    threshold - the inverse condition from ORB's filter). The current
    candidate approach.

WHY THIS EXISTS: manually tweaking one parameter at a time in TradingView
and re-testing against the same window is how you accidentally overfit to
noise. This script instead:

  1. Pulls free historical MNQ/MES data (Yahoo Finance).
  2. Splits it chronologically into an IN-SAMPLE period (used for search)
     and an OUT-OF-SAMPLE period (never touched during search).
  3. Grid-searches parameters on the in-sample data only.
  4. Scores parameter combos by ROBUSTNESS (median performance across
     nearby settings), not just whichever single combo peaked highest.
  5. Takes the most robust candidate and runs it ONCE, unchanged, on the
     out-of-sample data. That result - not the in-sample number - is the
     honest read on whether this has real edge.

Run locally (needs normal internet access - this cannot run inside the
sandboxed session that built it):

    python backtest_optimizer.py

This is a research/comparison tool for exploring parameter space quickly.
It is NOT a byte-for-byte replica of TradingView's fill/PnL accounting -
treat its numbers as directionally trustworthy for comparing configs
against each other, and always confirm a final candidate in TradingView's
Strategy Tester before considering it for demo trading.
"""

import itertools
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Yahoo's own limits per interval - requesting more than this just gets
# silently clamped, so these are the real ceilings on sample size.
INTERVAL_MAX_RANGE = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
}

POINT_VALUE = {"MNQ=F": 2.0, "MES=F": 5.0}
TICK_SIZE = {"MNQ=F": 0.25, "MES=F": 0.25}

SHARED_DEFAULTS = dict(
    atr_len=14, vol_len=20, vol_mult=1.5,
    base_size=3, add_size=3, max_size=9,
    stop_atr_mult=1.5, scale_in_atr_mult=1.0,
    target1_atr_mult=1.0, target2_atr_mult=2.0,
    session_start=(9, 30), session_end=(16, 0),
    commission_per_contract=1.0,
    slippage_ticks=2,
)

CROSSOVER_DEFAULTS = {**SHARED_DEFAULTS, **dict(
    fast_len=9, slow_len=21,
    use_trend_filter=True, trend_len=200,
    use_vwap_filter=True,
)}

ORB_DEFAULTS = {**SHARED_DEFAULTS, **dict(
    or_minutes=15,
    use_vwap_filter=True,
    use_adx_filter=True, adx_len=14, adx_threshold=20,
)}

CROSSOVER_GRID = dict(
    fast_len=[7, 9, 11],
    slow_len=[18, 21, 25],
    stop_atr_mult=[1.2, 1.5, 1.8],
    use_trend_filter=[True, False],
    use_vwap_filter=[True, False],
)

ORB_GRID = dict(
    or_minutes=[15],  # locked to 15 min per your traded setup
    adx_threshold=[15, 20, 25],
    stop_atr_mult=[1.2, 1.5, 1.8],
    use_vwap_filter=[True, False],
    use_adx_filter=[True, False],
)

MEANREV_DEFAULTS = {**SHARED_DEFAULTS, **dict(
    vwap_band_mult=2.0,
    adx_len=14, adx_threshold=20,   # note: LOW adx = range-bound = the condition we want here
    target_fraction_1=0.5,          # halfway back to VWAP
    target_fraction_2=1.0,          # full VWAP touch
    use_trend_alignment=True,       # only trade mean-reversion WITH/neutral to the broader trend
    trend_len=100,
)}

MEANREV_GRID = dict(
    vwap_band_mult=[1.5, 2.0, 2.5],
    adx_threshold=[15, 20, 25],
    stop_atr_mult=[1.0, 1.5, 2.0],
    vol_mult=[1.2, 1.5],
    use_trend_alignment=[True, False],
)


# ---------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------
def fetch_bars(symbol, interval):
    range_ = INTERVAL_MAX_RANGE[interval]
    resp = requests.get(
        YAHOO_URL.format(symbol=symbol),
        params={"interval": interval, "range": range_},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(f"No data returned for {symbol} {interval}: {data.get('chart', {}).get('error')}")

    result = result[0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(timestamps):
        o, h, l, c, v = (quote["open"][i], quote["high"][i], quote["low"][i],
                          quote["close"][i], quote["volume"][i])
        if None in (o, h, l, c, v):
            continue
        bars.append({
            "dt": datetime.fromtimestamp(ts, tz=ET),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return bars


def split_in_out_sample(bars, in_sample_frac=0.7):
    split_idx = int(len(bars) * in_sample_frac)
    return bars[:split_idx], bars[split_idx:]


# ---------------------------------------------------------------------
# Indicators (plain Python - no pandas/numpy required)
# ---------------------------------------------------------------------
def ema_series(values, length):
    k = 2 / (length + 1)
    out = []
    ema = None
    for v in values:
        ema = v if ema is None else v * k + ema * (1 - k)
        out.append(ema)
    return out


def true_range_series(bars):
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["high"] - b["low"])
        else:
            prev_close = bars[i - 1]["close"]
            trs.append(max(
                b["high"] - b["low"],
                abs(b["high"] - prev_close),
                abs(b["low"] - prev_close),
            ))
    return trs


def wilder_smooth(values, length):
    """Wilder's RMA smoothing - same style ta.atr/ta.rma use in Pine."""
    out = [None] * len(values)
    if len(values) < length:
        return out
    seed = statistics.mean(values[:length])
    out[length - 1] = seed
    smoothed = seed
    for i in range(length, len(values)):
        smoothed = (smoothed * (length - 1) + values[i]) / length
        out[i] = smoothed
    return out


def atr_series(bars, length):
    return wilder_smooth(true_range_series(bars), length)


def adx_series(bars, length):
    """Standard Wilder ADX: +DI/-DI from directional movement, DX, then
    Wilder-smoothed DX = ADX."""
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, len(bars)):
        up_move = bars[i]["high"] - bars[i - 1]["high"]
        down_move = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)

    trs = true_range_series(bars)
    smoothed_tr = wilder_smooth(trs, length)
    smoothed_plus_dm = wilder_smooth(plus_dm, length)
    smoothed_minus_dm = wilder_smooth(minus_dm, length)

    dx = [None] * len(bars)
    for i in range(len(bars)):
        if smoothed_tr[i] is None or not smoothed_tr[i]:
            continue
        plus_di = 100 * smoothed_plus_dm[i] / smoothed_tr[i]
        minus_di = 100 * smoothed_minus_dm[i] / smoothed_tr[i]
        denom = plus_di + minus_di
        dx[i] = 100 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0

    dx_clean = [v if v is not None else 0.0 for v in dx]
    adx = wilder_smooth(dx_clean, length)
    # Only valid once both the DI smoothing AND the DX smoothing have warmed up
    first_valid = next((i for i, v in enumerate(smoothed_tr) if v is not None), None)
    if first_valid is not None:
        for i in range(min(first_valid + length, len(adx))):
            adx[i] = None
    return adx


def sma_series(values, length):
    out = []
    for i in range(len(values)):
        out.append(None if i + 1 < length else statistics.mean(values[i + 1 - length:i + 1]))
    return out


def vwap_series(bars):
    """Session VWAP, resetting each ET calendar day - mirrors ta.vwap(hlc3)."""
    out = []
    cum_pv = cum_v = 0.0
    current_day = None
    for b in bars:
        day = b["dt"].date()
        if day != current_day:
            current_day = day
            cum_pv = cum_v = 0.0
        typical = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += typical * b["volume"]
        cum_v += b["volume"]
        out.append(cum_pv / cum_v if cum_v > 0 else None)
    return out


def opening_range_series(bars, or_minutes, session_start):
    """
    For each bar, returns (or_high, or_low, or_window_closed) using the
    running high/low of the first `or_minutes` of that day's session.
    or_window_closed is False for bars still inside the OR window itself
    (no breakout trading during OR formation).
    """
    sh, sm = session_start
    out = []
    current_day = None
    or_high = or_low = None
    or_end_dt = None
    for b in bars:
        day = b["dt"].date()
        if day != current_day:
            current_day = day
            or_high = or_low = None
            session_open_dt = b["dt"].replace(hour=sh, minute=sm, second=0, microsecond=0)
            or_end_dt = session_open_dt + timedelta(minutes=or_minutes)
        within_or_window = b["dt"] < or_end_dt
        if within_or_window:
            or_high = b["high"] if or_high is None else max(or_high, b["high"])
            or_low = b["low"] if or_low is None else min(or_low, b["low"])
            out.append((or_high, or_low, False))
        else:
            out.append((or_high, or_low, True))
    return out


# ---------------------------------------------------------------------
# Shared position management (scale in/out, stops, targets) - identical
# mechanics for both strategies, only the ENTRY trigger differs.
# ---------------------------------------------------------------------
def _in_session(dt, session_start, session_end):
    sh, sm = session_start
    eh, em = session_end
    t = (dt.hour, dt.minute)
    return (sh, sm) <= t <= (eh, em)


def _simulate(bars, symbol, p, entry_signal_fn):
    """
    entry_signal_fn(i, bars, precomputed) -> ("long" | "short" | None)
    precomputed is a dict of whatever series the caller needs available.
    """
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    atr = atr_series(bars, p["atr_len"])
    avg_vol = sma_series(volumes, p["vol_len"])

    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]

    position = None
    trade_cashflows = []

    def close_qty(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    for i in range(1, len(bars)):
        if atr[i] is None or avg_vol[i] is None:
            continue

        dt = bars[i]["dt"]
        price = closes[i]
        vol_confirmed = volumes[i] > avg_vol[i] * p["vol_mult"]
        can_trade = _in_session(dt, p["session_start"], p["session_end"])

        if position is not None:
            direction = position["direction"]
            stop_hit = (direction == "long" and price <= position["stop"]) or \
                       (direction == "short" and price >= position["stop"])
            if stop_hit:
                close_qty(direction, position["size"], price, position["avg_entry"])
                position = None
                continue

            favorable = (price - position["last_scale_price"]) if direction == "long" \
                else (position["last_scale_price"] - price)
            if (can_trade and position["size"] < p["max_size"]
                    and favorable >= atr[i] * p["scale_in_atr_mult"] and vol_confirmed):
                add_qty = min(p["add_size"], p["max_size"] - position["size"])
                fill_price = price + slippage_price if direction == "long" else price - slippage_price
                prior_cost = position["avg_entry"] * position["size"]
                position["avg_entry"] = (prior_cost + fill_price * add_qty) / (position["size"] + add_qty)
                position["size"] += add_qty
                position["last_scale_price"] = price
                position["stop"] = price - atr[i] if direction == "long" else price + atr[i]
                trade_cashflows.append(-p["commission_per_contract"] * add_qty)
                continue

            t1 = position["last_scale_price"] + atr[i] * p["target1_atr_mult"] if direction == "long" \
                else position["last_scale_price"] - atr[i] * p["target1_atr_mult"]
            t2 = position["last_scale_price"] + atr[i] * p["target2_atr_mult"] if direction == "long" \
                else position["last_scale_price"] - atr[i] * p["target2_atr_mult"]
            hit_t1 = (direction == "long" and price >= t1) or (direction == "short" and price <= t1)
            hit_t2 = (direction == "long" and price >= t2) or (direction == "short" and price <= t2)

            if hit_t2 and not position["target2_hit"] and position["size"] > 1:
                trim = max(1, position["size"] // 3)
                close_qty(direction, trim, price, position["avg_entry"])
                position["size"] -= trim
                if position["size"] <= 0:
                    position = None
                else:
                    position["target2_hit"] = True
                    position["stop"] = position["last_scale_price"]
                continue
            elif hit_t1 and not position["target1_hit"] and position["size"] > 1:
                trim = max(1, position["size"] // 3)
                close_qty(direction, trim, price, position["avg_entry"])
                position["size"] -= trim
                if position["size"] <= 0:
                    position = None
                else:
                    position["target1_hit"] = True
                continue

        if position is None and can_trade:
            signal = entry_signal_fn(i, vol_confirmed)
            if signal in ("long", "short"):
                direction = signal
                fill_price = price + slippage_price if direction == "long" else price - slippage_price
                stop = price - atr[i] * p["stop_atr_mult"] if direction == "long" else price + atr[i] * p["stop_atr_mult"]
                position = dict(direction=direction, size=p["base_size"], avg_entry=fill_price,
                                 last_scale_price=price, stop=stop,
                                 target1_hit=False, target2_hit=False)
                trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])

    gross_profit = sum(c for c in trade_cashflows if c > 0)
    gross_loss = -sum(c for c in trade_cashflows if c < 0)
    net = sum(trade_cashflows)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    return dict(
        events=len(trade_cashflows), net_pnl=net,
        gross_profit=gross_profit, gross_loss=gross_loss,
        profit_factor=profit_factor,
    )


# ---------------------------------------------------------------------
# Strategy 1: EMA crossover (reference only - known to lack edge)
# ---------------------------------------------------------------------
def run_backtest_crossover(bars, symbol, params):
    p = {**CROSSOVER_DEFAULTS, **params}
    closes = [b["close"] for b in bars]

    ema_fast = ema_series(closes, p["fast_len"])
    ema_slow = ema_series(closes, p["slow_len"])
    trend_ema = ema_series(closes, p["trend_len"])
    vwap = vwap_series(bars)

    def entry_signal(i, vol_confirmed):
        if ema_slow[i] is None or (p["use_trend_filter"] and trend_ema[i] is None) \
                or (p["use_vwap_filter"] and vwap[i] is None):
            return None
        price = closes[i]
        cross_up = ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]
        cross_down = ema_fast[i - 1] >= ema_slow[i - 1] and ema_fast[i] < ema_slow[i]
        if p["use_trend_filter"]:
            cross_up = cross_up and price > trend_ema[i]
            cross_down = cross_down and price < trend_ema[i]
        if p["use_vwap_filter"]:
            cross_up = cross_up and price > vwap[i]
            cross_down = cross_down and price < vwap[i]
        if cross_up and vol_confirmed:
            return "long"
        if cross_down and vol_confirmed:
            return "short"
        return None

    return _simulate(bars, symbol, p, entry_signal)


# ---------------------------------------------------------------------
# Strategy 2: Opening Range Breakout + VWAP + Volume + ADX (current candidate)
# ---------------------------------------------------------------------
def run_backtest_orb(bars, symbol, params):
    p = {**ORB_DEFAULTS, **params}
    closes = [b["close"] for b in bars]

    vwap = vwap_series(bars)
    adx = adx_series(bars, p["adx_len"])
    or_data = opening_range_series(bars, p["or_minutes"], p["session_start"])

    def entry_signal(i, vol_confirmed):
        or_high, or_low, or_closed = or_data[i]
        if not or_closed or or_high is None or or_low is None:
            return None
        if p["use_vwap_filter"] and vwap[i] is None:
            return None
        if p["use_adx_filter"] and adx[i] is None:
            return None

        price = closes[i]
        breakout_up = price > or_high
        breakout_down = price < or_low

        if p["use_vwap_filter"]:
            breakout_up = breakout_up and price > vwap[i]
            breakout_down = breakout_down and price < vwap[i]
        if p["use_adx_filter"]:
            breakout_up = breakout_up and adx[i] >= p["adx_threshold"]
            breakout_down = breakout_down and adx[i] >= p["adx_threshold"]

        if breakout_up and vol_confirmed:
            return "long"
        if breakout_down and vol_confirmed:
            return "short"
        return None

    return _simulate(bars, symbol, p, entry_signal)


# ---------------------------------------------------------------------
# Strategy 3: VWAP mean-reversion in range-bound conditions (current candidate)
#
# Targets are relative to VWAP at entry (halfway back, full touch) rather
# than open-ended ATR extensions, since the whole thesis is "reverts to
# the mean," not "keeps running" - this has its own simulation loop
# instead of reusing _simulate/entry_signal, because the target logic is
# structurally different (VWAP-relative, not last-scale-price-relative).
# ---------------------------------------------------------------------
def run_backtest_meanrev(bars, symbol, params):
    p = {**MEANREV_DEFAULTS, **params}
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    atr = atr_series(bars, p["atr_len"])
    avg_vol = sma_series(volumes, p["vol_len"])
    vwap = vwap_series(bars)
    adx = adx_series(bars, p["adx_len"])
    trend_ema = ema_series(closes, p["trend_len"])

    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]

    position = None
    trade_cashflows = []

    def close_qty(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    for i in range(1, len(bars)):
        if atr[i] is None or avg_vol[i] is None or vwap[i] is None or adx[i] is None:
            continue
        if p["use_trend_alignment"] and trend_ema[i] is None:
            continue

        dt = bars[i]["dt"]
        price = closes[i]
        vol_confirmed = volumes[i] > avg_vol[i] * p["vol_mult"]
        can_trade = _in_session(dt, p["session_start"], p["session_end"])
        range_bound = adx[i] < p["adx_threshold"]

        upper_band = vwap[i] + atr[i] * p["vwap_band_mult"]
        lower_band = vwap[i] - atr[i] * p["vwap_band_mult"]

        if position is not None:
            direction = position["direction"]
            stop_hit = (direction == "long" and price <= position["stop"]) or \
                       (direction == "short" and price >= position["stop"])
            if stop_hit:
                close_qty(direction, position["size"], price, position["avg_entry"])
                position = None
                continue

            favorable = (price - position["last_scale_price"]) if direction == "long" \
                else (position["last_scale_price"] - price)
            if (can_trade and position["size"] < p["max_size"]
                    and favorable >= atr[i] * p["scale_in_atr_mult"] and vol_confirmed):
                add_qty = min(p["add_size"], p["max_size"] - position["size"])
                fill_price = price + slippage_price if direction == "long" else price - slippage_price
                prior_cost = position["avg_entry"] * position["size"]
                position["avg_entry"] = (prior_cost + fill_price * add_qty) / (position["size"] + add_qty)
                position["size"] += add_qty
                position["last_scale_price"] = price
                trade_cashflows.append(-p["commission_per_contract"] * add_qty)
                continue

            entry_vwap_distance = (position["entry_vwap"] - position["entry_price"]) if direction == "long" \
                else (position["entry_price"] - position["entry_vwap"])
            target1 = position["entry_price"] + entry_vwap_distance * p["target_fraction_1"] if direction == "long" \
                else position["entry_price"] - entry_vwap_distance * p["target_fraction_1"]
            target2 = position["entry_price"] + entry_vwap_distance * p["target_fraction_2"] if direction == "long" \
                else position["entry_price"] - entry_vwap_distance * p["target_fraction_2"]

            hit_t1 = (direction == "long" and price >= target1) or (direction == "short" and price <= target1)
            hit_t2 = (direction == "long" and price >= target2) or (direction == "short" and price <= target2)

            if hit_t2 and not position["target2_hit"]:
                close_qty(direction, position["size"], price, position["avg_entry"])
                position = None
                continue
            elif hit_t1 and not position["target1_hit"] and position["size"] > 1:
                trim = max(1, position["size"] // 2)
                close_qty(direction, trim, price, position["avg_entry"])
                position["size"] -= trim
                if position["size"] <= 0:
                    position = None
                else:
                    position["target1_hit"] = True
                continue

        # Trend alignment: don't buy dips fighting a clear downtrend, and
        # don't short rallies fighting a clear uptrend - only trade
        # mean-reversion aligned with or neutral to the broader trend.
        long_trend_ok = (not p["use_trend_alignment"]) or price >= trend_ema[i]
        short_trend_ok = (not p["use_trend_alignment"]) or price <= trend_ema[i]

        if position is None and can_trade and range_bound:
            if price <= lower_band and vol_confirmed and long_trend_ok:
                fill_price = price + slippage_price
                position = dict(direction="long", size=p["base_size"], avg_entry=fill_price,
                                 last_scale_price=price, stop=price - atr[i] * p["stop_atr_mult"],
                                 entry_price=price, entry_vwap=vwap[i],
                                 target1_hit=False, target2_hit=False)
                trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])
            elif price >= upper_band and vol_confirmed and short_trend_ok:
                fill_price = price - slippage_price
                position = dict(direction="short", size=p["base_size"], avg_entry=fill_price,
                                 last_scale_price=price, stop=price + atr[i] * p["stop_atr_mult"],
                                 entry_price=price, entry_vwap=vwap[i],
                                 target1_hit=False, target2_hit=False)
                trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])

    gross_profit = sum(c for c in trade_cashflows if c > 0)
    gross_loss = -sum(c for c in trade_cashflows if c < 0)
    net = sum(trade_cashflows)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    return dict(
        events=len(trade_cashflows), net_pnl=net,
        gross_profit=gross_profit, gross_loss=gross_loss,
        profit_factor=profit_factor,
    )


STRATEGIES = {
    "crossover": dict(run=run_backtest_crossover, grid=CROSSOVER_GRID, group_by=("fast_len", "slow_len")),
    "orb": dict(run=run_backtest_orb, grid=ORB_GRID, group_by=("adx_threshold",)),
    "meanrev": dict(run=run_backtest_meanrev, grid=MEANREV_GRID, group_by=("use_trend_alignment", "vwap_band_mult")),
}


# ---------------------------------------------------------------------
# Grid search + robustness scoring (strategy-agnostic)
# ---------------------------------------------------------------------
def grid_search(bars_in_sample, symbol, run_fn, grid):
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        stats = run_fn(bars_in_sample, symbol, params)
        results.append((params, stats))
    return results


def robust_candidates(results, group_by, top_n=3):
    """
    Groups results by the structurally important param(s) in group_by and
    scores each group by the MEDIAN profit factor across all other param
    variations tested with that group - a config that's only good with one
    exact combination of secondary settings is fragile; one that's good
    across most of them is more trustworthy.
    """
    by_group = {}
    for params, stats in results:
        key = tuple(params[k] for k in group_by)
        by_group.setdefault(key, []).append((params, stats))

    group_scores = []
    for key, entries in by_group.items():
        pfs = [s["profit_factor"] for _, s in entries if s["events"] >= 10]
        if len(pfs) < 3:
            continue
        median_pf = statistics.median(pfs)
        best_params, best_stats = max(entries, key=lambda e: e[1]["profit_factor"])
        group_scores.append((key, median_pf, best_params, best_stats))

    group_scores.sort(key=lambda x: x[1], reverse=True)
    return group_scores[:top_n]


# ---------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------
def run_for(symbol, interval, strategy_name):
    strat = STRATEGIES[strategy_name]
    print(f"\n{'=' * 70}\n{symbol}  |  {interval}  |  strategy={strategy_name}\n{'=' * 70}")
    try:
        bars = fetch_bars(symbol, interval)
    except Exception as e:
        print(f"  Could not fetch data: {type(e).__name__}: {e}")
        return

    print(f"  Fetched {len(bars)} bars ({bars[0]['dt'].date()} to {bars[-1]['dt'].date()})")
    if len(bars) < 300:
        print("  Not enough bars for a meaningful in-sample/out-of-sample split. Skipping.")
        return

    in_sample, out_sample = split_in_out_sample(bars)
    print(f"  In-sample:  {len(in_sample)} bars ({in_sample[0]['dt'].date()} to {in_sample[-1]['dt'].date()})")
    print(f"  Out-sample: {len(out_sample)} bars ({out_sample[0]['dt'].date()} to {out_sample[-1]['dt'].date()})")

    results = grid_search(in_sample, symbol, strat["run"], strat["grid"])
    top = robust_candidates(results, strat["group_by"])

    if not top:
        print("  No candidate had enough trades in-sample to evaluate. Try a longer interval.")
        return

    print(f"\n  Most robust {strat['group_by']} groupings (by median profit factor across settings):")
    for rank, (key, median_pf, best_params, best_in_sample_stats) in enumerate(top, 1):
        print(f"\n  #{rank}: {dict(zip(strat['group_by'], key))}  "
              f"(in-sample median PF across variants: {median_pf:.3f})")
        print(f"      Best in-sample combo: {best_params}")
        print(f"      In-sample result: PF={best_in_sample_stats['profit_factor']:.3f}  "
              f"events={best_in_sample_stats['events']}  net=${best_in_sample_stats['net_pnl']:.2f}")

        oos_stats = strat["run"](out_sample, symbol, best_params)
        print(f"      OUT-OF-SAMPLE result: PF={oos_stats['profit_factor']:.3f}  "
              f"events={oos_stats['events']}  net=${oos_stats['net_pnl']:.2f}")
        if oos_stats["profit_factor"] >= 1.0:
            print("      -> Held up out-of-sample. Worth taking to TradingView for final confirmation.")
        else:
            print("      -> Did NOT hold up out-of-sample. Treat the in-sample number as noise, not edge.")


def main():
    for symbol in ["MNQ=F", "MES=F"]:
        for interval in ["1m", "5m", "15m"]:
            run_for(symbol, interval, "meanrev")


if __name__ == "__main__":
    main()
