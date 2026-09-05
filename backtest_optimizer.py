"""
Walk-forward parameter robustness search for the VWAP Pullback
Trend-Continuation strategy on MNQ.

This file used to carry seven strategy families (crossover, ORB, mean-
reversion, scalp at two target scales, a liquidity-sweep swing trade,
and a UT Bot port). All of them were tried, tested against real data,
and either failed outright or raised unresolved problems (mean-reversion
turned out to be outlier-dependent with a sub-50% win rate; ORB, EMA
crossover, both scalp variants, and the liquidity sweep never showed
real out-of-sample edge; UT Bot's most-supported result was a decisive
loser). Per a decision to stop spreading effort across candidates and
get serious about the one strategy that's actually held up, all of that
was stripped out. Their code, walk-forward results, and real TradingView
confirmations are preserved in this repo's git history if any of them is
ever worth revisiting - they are not gone, just no longer cluttering the
active file.

"vwap_pullback": trend-continuation - trades WITH a moderate trend (ADX
in a band, not range-bound) on pullbacks TO VWAP that hold (a rejection
candle), entering on a breakout of that candle's high/low. MNQ only (MES
was tested and dropped - real TradingView results never held up on MES
the way they did on MNQ). Real TradingView confirmation on the 5-minute
default (1.5x ATR stop, 3-9 contracts): PF 1.527, 52 trades, $4,928 net -
BUT $3,570 max drawdown against the account's real $2,000 EOD trailing
drawdown limit, so that exact config was not tradeable as sized.
Tighter stops (down to 0.5x ATR) were tried specifically to allow more
size and confirmed to NOT work (OOS PF 0.000, pure losses) - the fix is
reduced position size at the original 1.5x ATR stop, not a tighter stop.
The original 1.5x-ATR/ADX-15-30 config has kept holding up across
multiple rolling-data re-runs since, most recently PF 1.763 on 29
out-of-sample trades with $1,210.50 max drawdown (under the $1,300
safety budget at default 3/3/9 sizing on that window) - this is the one
real, repeatable signal to come out of this whole project so far.
15-minute has no real edge (PF ~1.05 on real TradingView data) and stays
in the grid only as a standing comparison, not because it's expected to
improve.

WHY THIS EXISTS: manually tweaking one parameter at a time in TradingView
and re-testing against the same window is how you accidentally overfit to
noise. This script instead:

  1. Pulls free historical MNQ data (Yahoo Finance).
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
from datetime import datetime
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

POINT_VALUE = {"MNQ=F": 2.0}
TICK_SIZE = {"MNQ=F": 0.25}

SHARED_DEFAULTS = dict(
    atr_len=14, vol_len=20, vol_mult=1.5,
    base_size=3, add_size=3, max_size=9,
    stop_atr_mult=1.5, scale_in_atr_mult=1.0,
    target1_atr_mult=1.0, target2_atr_mult=2.0,
    session_start=(9, 30), session_end=(16, 0),
    commission_per_contract=1.0,
    slippage_ticks=2,
)

VWAPPB_DEFAULTS = {**SHARED_DEFAULTS, **dict(
    adx_len=14, adx_low=20, adx_high=35,   # trending-but-not-extreme
    trend_fast_len=20, trend_slow_len=50,
    breakout_window=5,                     # bars to wait for the rejection candle's high/low to break
)}

VWAPPB_GRID = dict(
    adx_low=[15, 20, 25],
    adx_high=[30, 35, 40],
    trend_fast_len=[10, 20],
    trend_slow_len=[50, 100],
    # Real TradingView test of the 1.5x-ATR default (MNQ 5m, 3-9 contracts)
    # came back PF 1.527 / 52 trades but with a $3,570 max drawdown against
    # a confirmed $2,000 account trailing drawdown limit - tighter stops
    # are in the grid to see whether a smaller per-trade risk can hold the
    # same edge while fitting the real risk budget. TESTED and confirmed
    # NOT to work (0.5x-ATR OOS PF 0.000) - kept in the grid so re-runs
    # keep reconfirming that, not because it's expected to change.
    stop_atr_mult=[0.5, 0.75, 1.0, 1.5, 2.0],
)

# Tradeify account's real EOD trailing drawdown limit (user-confirmed) and
# a conservative safety budget under it - use these to size positions from
# the risk budget, not from margin/contract-count capacity (margin capacity
# is a much larger, unrelated ceiling and sizing off it will blow the
# account on the first bad stretch).
ACCOUNT_TRAILING_DRAWDOWN_LIMIT = 2000.0
DRAWDOWN_SAFETY_BUDGET = 1300.0


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


# ---------------------------------------------------------------------
# Shared position management (scale in/out, stops, targets)
# ---------------------------------------------------------------------
def _in_session(dt, session_start, session_end):
    sh, sm = session_start
    eh, em = session_end
    t = (dt.hour, dt.minute)
    return (sh, sm) <= t <= (eh, em)


def _max_drawdown(trade_cashflows):
    """
    Peak-to-trough drawdown on the CLOSED-TRADE equity curve (cumulative
    realized cashflows in the order they occurred) - not an intrabar
    mark-to-market curve. This is the number that matters for a prop
    account's trailing drawdown rule: a strategy can look great on profit
    factor alone while still blowing through the account's hard drawdown
    limit on the way there, which is exactly what real TradingView testing
    caught (max_drawdown $3,570 against a $2,000 EOD trailing limit on the
    vwap_pullback 5m/3x9-contract config) - PF was never enough by itself.
    """
    equity = peak = max_dd = 0.0
    for cf in trade_cashflows:
        equity += cf
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _simulate(bars, symbol, p, entry_signal_fn):
    """
    entry_signal_fn(i, vol_confirmed) -> ("long" | "short" | None)
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
        max_drawdown=_max_drawdown(trade_cashflows),
    )


# ---------------------------------------------------------------------
# VWAP pullback trend-continuation
#
# Trades WITH a moderate trend (ADX in a band, not range-bound), entering
# on pullbacks TO VWAP that hold. Two-stage signal: a "rejection candle"
# (touches VWAP, closes back on the trend side) sets up a pending
# breakout level; a later bar breaking that level triggers the actual
# entry. Reuses _simulate's shared scale-in/out/stop/target engine via a
# stateful entry_signal closure.
# ---------------------------------------------------------------------
def run_backtest_vwap_pullback(bars, symbol, params):
    p = {**VWAPPB_DEFAULTS, **params}
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    opens = [b["open"] for b in bars]

    vwap = vwap_series(bars)
    adx = adx_series(bars, p["adx_len"])
    trend_fast = ema_series(closes, p["trend_fast_len"])
    trend_slow = ema_series(closes, p["trend_slow_len"])

    pending = {"direction": None, "trigger": None, "bars_left": 0}

    def entry_signal(i, vol_confirmed):
        if adx[i] is None or vwap[i] is None or trend_fast[i] is None or trend_slow[i] is None:
            return None

        if pending["direction"] == "long":
            if highs[i] >= pending["trigger"]:
                pending["direction"] = None
                return "long"
            pending["bars_left"] -= 1
            if pending["bars_left"] <= 0:
                pending["direction"] = None
        elif pending["direction"] == "short":
            if lows[i] <= pending["trigger"]:
                pending["direction"] = None
                return "short"
            pending["bars_left"] -= 1
            if pending["bars_left"] <= 0:
                pending["direction"] = None

        if pending["direction"] is not None:
            return None  # still waiting on an existing pending setup

        regime_trending = p["adx_low"] <= adx[i] <= p["adx_high"]
        if not regime_trending:
            return None

        uptrend = trend_fast[i] > trend_slow[i]
        downtrend = trend_fast[i] < trend_slow[i]

        # Rejection candle: dipped to/through VWAP then closed back on the trend side
        if uptrend and lows[i] <= vwap[i] and closes[i] > vwap[i] and closes[i] > opens[i] and vol_confirmed:
            pending["direction"] = "long"
            pending["trigger"] = highs[i]
            pending["bars_left"] = p["breakout_window"]
        elif downtrend and highs[i] >= vwap[i] and closes[i] < vwap[i] and closes[i] < opens[i] and vol_confirmed:
            pending["direction"] = "short"
            pending["trigger"] = lows[i]
            pending["bars_left"] = p["breakout_window"]

        return None

    return _simulate(bars, symbol, p, entry_signal)


STRATEGIES = {
    "vwap_pullback": dict(run=run_backtest_vwap_pullback, grid=VWAPPB_GRID, group_by=("adx_low", "adx_high")),
}


# ---------------------------------------------------------------------
# Grid search + robustness scoring
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


def suggest_size_for_budget(max_drawdown, base_size, max_size, budget=DRAWDOWN_SAFETY_BUDGET):
    """
    Rough linear-scaling estimate only - drawdown scales with position size
    because the entry/exit price logic doesn't change, but this is NOT a
    substitute for re-running the backtest at the suggested size. Treat it
    as a starting point to test, not a validated answer.
    """
    if max_drawdown <= 0:
        return base_size, max_size
    scale = min(1.0, budget / max_drawdown)
    return max(1, round(base_size * scale)), max(1, round(max_size * scale))


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
              f"events={best_in_sample_stats['events']}  net=${best_in_sample_stats['net_pnl']:.2f}  "
              f"max_drawdown=${best_in_sample_stats['max_drawdown']:.2f}")

        oos_stats = strat["run"](out_sample, symbol, best_params)
        print(f"      OUT-OF-SAMPLE result: PF={oos_stats['profit_factor']:.3f}  "
              f"events={oos_stats['events']}  net=${oos_stats['net_pnl']:.2f}  "
              f"max_drawdown=${oos_stats['max_drawdown']:.2f}")
        if oos_stats["profit_factor"] >= 1.0:
            print("      -> Held up out-of-sample. Worth taking to TradingView for final confirmation.")
        else:
            print("      -> Did NOT hold up out-of-sample. Treat the in-sample number as noise, not edge.")

        if oos_stats["max_drawdown"] > DRAWDOWN_SAFETY_BUDGET:
            print(f"      !! max_drawdown ${oos_stats['max_drawdown']:.2f} exceeds the "
                  f"${DRAWDOWN_SAFETY_BUDGET:.0f} safety budget (real account trailing "
                  f"drawdown limit: ${ACCOUNT_TRAILING_DRAWDOWN_LIMIT:.0f}).")
            # base_size/max_size are never swept in VWAPPB_GRID, so they're
            # never in best_params (which only holds the grid keys that
            # were actually varied) - fall back to the defaults that were
            # actually used at runtime (run_backtest_vwap_pullback merges
            # {**VWAPPB_DEFAULTS, **params} internally).
            base_size = best_params.get("base_size", VWAPPB_DEFAULTS["base_size"])
            max_size = best_params.get("max_size", VWAPPB_DEFAULTS["max_size"])
            sug_base, sug_max = suggest_size_for_budget(oos_stats["max_drawdown"], base_size, max_size)
            print(f"      -> Rough linear-scaling suggestion: base_size={sug_base}, "
                  f"max_size={sug_max} (was {base_size}/{max_size}). "
                  f"RE-RUN at this size to confirm, don't just trust the scaling math - "
                  f"stop-loss noise doesn't scale perfectly linearly in practice.")


# ---------------------------------------------------------------------
# Sizing sweep - the confirmed-good config (ADX 15-30, trend EMA 10/50,
# 1.5x ATR stop) at several explicit contract sizes, so ONE run answers
# "what size actually fits the account" instead of guessing from
# linear-scaling math or testing one size per round trip. Runs on the
# FULL dataset (not in-sample/out-of-sample split) since sizing isn't
# being searched/optimized here - only the ADX/trend/stop parameters
# were walk-forward tested, sizing is a separate, later question about
# an already-fixed signal, so there's no overfitting risk in using all
# the data to answer it.
#
# PF should stay roughly flat across sizes (win/loss ratio doesn't
# change with contract count, aside from integer-rounding on partial
# exits) - the number that actually MOVES with size, and the one that
# matters, is max_drawdown. That's what determines which sizes are
# actually safe for the account's $2,000 limit.
# ---------------------------------------------------------------------
SIZE_SWEEP_CONFIG = dict(
    adx_low=15, adx_high=30,
    trend_fast_len=10, trend_slow_len=50,
    stop_atr_mult=1.5,
)

SIZE_CANDIDATES = [
    (1, 2), (1, 3), (1, 4), (2, 4), (2, 6), (3, 6), (3, 9),
]


def run_sizing_sweep(symbol="MNQ=F", interval="5m"):
    print(f"\n{'=' * 70}\nSIZING SWEEP  |  {symbol}  |  {interval}  |  "
          f"fixed config: {SIZE_SWEEP_CONFIG}\n{'=' * 70}")
    try:
        bars = fetch_bars(symbol, interval)
    except Exception as e:
        print(f"  Could not fetch data: {type(e).__name__}: {e}")
        return

    print(f"  Fetched {len(bars)} bars ({bars[0]['dt'].date()} to {bars[-1]['dt'].date()}) - full dataset, no split")
    print(f"  (safety budget: ${DRAWDOWN_SAFETY_BUDGET:.0f}  |  hard account limit: ${ACCOUNT_TRAILING_DRAWDOWN_LIMIT:.0f})\n")

    for base, mx in SIZE_CANDIDATES:
        params = {**SIZE_SWEEP_CONFIG, "base_size": base, "max_size": mx}
        stats = run_backtest_vwap_pullback(bars, symbol, params)
        dd = stats["max_drawdown"]
        if dd > ACCOUNT_TRAILING_DRAWDOWN_LIMIT:
            flag = "  !! EXCEEDS THE $2,000 HARD LIMIT - not tradeable at this size"
        elif dd > DRAWDOWN_SAFETY_BUDGET:
            flag = "  !! over the $1,300 safety budget"
        else:
            flag = "  OK - within safety budget"
        print(f"  base={base}  max={mx}:  PF={stats['profit_factor']:.3f}  "
              f"events={stats['events']}  net=${stats['net_pnl']:.2f}  "
              f"max_drawdown=${dd:.2f}{flag}")


# ---------------------------------------------------------------------
# Live config check - runs the EXACT parameters currently live in
# jarvis_vwap_pullback_mnq.pine (as of Sept 2026: base=7/addSize=0/
# max=7, breakoutWindow=1, volMult=1.6 - all live-only adjustments made
# after the original walk-forward search, never independently tested
# here until now). This is NOT a grid search or an in/out-of-sample
# split - it's a single, exact-match run on the full available dataset,
# meant purely as an independent cross-check: does an untouched Python
# re-implementation, on Yahoo's data (a different source than
# TradingView's), agree with what TradingView has been showing? Yahoo's
# 60-day cap on 5-minute data still applies - this cannot reach back 2
# years, only as far as Yahoo's API allows, and won't be the exact same
# 60 days TradingView's own tests have used, which is exactly the point
# of an independent check.
# ---------------------------------------------------------------------
LIVE_CONFIG = dict(
    adx_low=15, adx_high=30,
    trend_fast_len=10, trend_slow_len=50,
    breakout_window=1,
    vol_mult=1.6,
    stop_atr_mult=1.5,
    scale_in_atr_mult=1.0,
    target1_atr_mult=1.0, target2_atr_mult=2.0,
    base_size=7, add_size=0, max_size=7,
)


def run_live_config_check(symbol="MNQ=F", interval="5m"):
    print(f"\n{'=' * 70}\nLIVE CONFIG CHECK  |  {symbol}  |  {interval}  |  "
          f"exact current live settings: {LIVE_CONFIG}\n{'=' * 70}")
    try:
        bars = fetch_bars(symbol, interval)
    except Exception as e:
        print(f"  Could not fetch data: {type(e).__name__}: {e}")
        return

    print(f"  Fetched {len(bars)} bars ({bars[0]['dt'].date()} to {bars[-1]['dt'].date()}) - "
          f"full dataset, no split (Yahoo's 60-day cap on 5m data, not a choice made here)")

    stats = run_backtest_vwap_pullback(bars, symbol, LIVE_CONFIG)
    dd = stats["max_drawdown"]
    print(f"  PF={stats['profit_factor']:.3f}  events={stats['events']}  "
          f"net=${stats['net_pnl']:.2f}  max_drawdown=${dd:.2f}")
    print(f"  (compare against the $150K account's real $5,250 EOD trailing drawdown limit)")


def main():
    # vwap_pullback only. See module docstring for why everything else
    # that used to run here was removed. Still running both 5m/15m each
    # time: 5m keeps reconfirming the real signal on fresh data, 15m
    # stays as a standing comparison (no real edge, not expected to
    # change) rather than something to chase.
    for interval in ["5m", "15m"]:
        run_for("MNQ=F", interval, "vwap_pullback")

    # Sizing sweep on the confirmed-good 5m config - answers "what size
    # actually fits the account" directly instead of via linear-scaling
    # guesses. See function docstring above.
    run_sizing_sweep("MNQ=F", "5m")

    # Independent check of the exact current live settings (base=7,
    # breakoutWindow=1, volMult=1.6) against Yahoo's data - see function
    # docstring above.
    run_live_config_check("MNQ=F", "5m")


if __name__ == "__main__":
    main()
