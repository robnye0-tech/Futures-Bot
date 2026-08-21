"""
Walk-forward parameter robustness search for the futures scale-in-out
strategy. Supports four entry-signal families:

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
    candidate approach. Also supports an optional trend-alignment filter
    (EMA-based) and OBV volume-trend confirmation, both toggleable -
    stacking both together can over-restrict the sample size (confirmed
    both on real TradingView data and in this script's own smoke test),
    so the report compares all four on/off combinations rather than
    assuming more filters = better. Real TradingView confirmation (not
    just this script): MNQ 5m held up with real costs (PF 1.185-1.403,
    ~100+ trades); MES 5m did NOT hold up on the same real period despite
    a strong signal in this script's earlier search - treat MNQ 5m as the
    one currently-trustworthy result, not MES.
  - "vwap_pullback": trend-continuation - the OPPOSITE regime and
    direction from meanrev. Trades WITH a moderate trend (ADX 20-35, not
    range-bound) on pullbacks TO VWAP that hold (a rejection candle),
    entering on a breakout of that candle's high/low. MNQ only (MES
    dropped, see below). Real TradingView confirmation on the 5-minute
    default (1.5x ATR stop, 3-9 contracts): PF 1.527, 52 trades, $4,928
    net - BUT $3,570 max drawdown against the account's real $2,000 EOD
    trailing drawdown limit, so that exact config is not tradeable as
    sized. 15-minute (ADX 20-40, EMA 10/100 - the config this search
    found) came back PF ~1.05 on real data - no real edge, don't use.
    Grid now includes tighter stop_atr_mult values (down to 0.5x) -
    TESTED, and it does NOT work: 0.5x-ATR configs came back OOS PF
    0.000 (pure losses). The fix for the drawdown problem is reduced
    size at the original 1.5x ATR stop, not a tighter stop - see
    ACCOUNT_TRAILING_DRAWDOWN_LIMIT / DRAWDOWN_SAFETY_BUDGET and the
    size suggestion printed in the report.
  - "scalp": fixed point target/stop, no scale-in/out, auto-close -
    entry on a fresh VWAP cross confirmed by fast EMA momentum and a
    volume spike. MNQ only.
    FIRST VERSION (target 8-15pts, noise-scale on MNQ): this script's own
    search showed OOS PF 1.449, 48 trades - looked real. Real TradingView
    result on the same config: PF 1.067, win rate 34.69% (barely above
    the mathematical breakeven of 33.3% for its own 2:1 reward:risk),
    equity curve gave back 80%+ of its peak - NO REAL EDGE, same failure
    pattern as MES mean-reversion (approximation overstated a signal real
    fills didn't back up). DEAD, don't pursue that exact config further.
    SECOND VERSION (target 20-40pts, a real momentum-scale move instead
    of a noise-scale one) - TESTED, also DEAD. All three top candidates
    (30/20, 35/20, 30/12 target/stop) showed out-of-sample PF below 1.0
    (0.793, 0.865, 0.811) with real sample sizes (50-52 OOS trades each,
    not a thin fluke) - the entry trigger itself doesn't have real edge
    at either target scale. Didn't need a TradingView round-trip to
    confirm this one; the Python result was already consistent and
    decisive across multiple settings. DEAD - don't pursue this entry
    signal (fresh VWAP cross + EMA momentum + volume) further at any
    target scale without a fundamentally different trigger.
  - "liquidity_sweep": swing-trade, multi-timeframe confluence - 4-hour
    structure (liquidity pools = rolling N-bar high/low, built by
    resampling 60-minute bars since Yahoo has no native 4h interval) for
    the setup, 1-hour for the entry trigger. A "sweep" is a 4h bar whose
    high/low exceeds the recent N-bar extreme AND closes back inside it
    (rejection) - same rejection-then-breakout shape as vwap_pullback,
    just applied to a rolling price extreme instead of VWAP, and to 4h
    structure instead of same-timeframe. Entry triggers on a 1h close
    beyond ITS OWN recent N-bar extreme in the reversal direction (break
    of structure). No fixed take-profit - the stop trails to newly-formed
    1h structure in the trade's favor instead. Position size (1-5
    contracts, per user's stated range) is computed FROM the stop
    distance to target a fixed risk_pct of a $2,000 CASH account (a
    different account from the Tradeify prop account and its $2,000
    trailing drawdown limit - same number, unrelated accounts, don't
    conflate them) - risk_pct defaults to 1% ($20/trade), NOT the
    originally-proposed 20% ($400/trade), which would risk account ruin
    in ~5 losing trades even at a real-world win rate. Uses 60-minute
    data, which Yahoo allows up to ~2 years back - a much longer real
    backtest window than any 5m/15m strategy here has ever gotten.
    FIRST REAL RUN found a genuine sizing bug, not just a weak result:
    max drawdown came back near/over the entire $2,000 account (e.g.
    $2,288) even at risk_pct=0.01 ($20/trade target) - caused by flooring
    position size to a minimum of 1 contract even when the stop was too
    wide for 1 contract to fit the risk budget, silently risking far more
    than intended on exactly the widest-stop trades. FIXED: a trade is
    now SKIPPED (not floored to 1 contract) whenever the stop is too wide
    for even 1 contract to fit risk_pct - standard risk-based position
    sizing practice (skip setups your account can't size properly for,
    don't force them). Also fixed the report's drawdown-budget check,
    which was printing the Tradeify prop account's $2,000/$1,300 numbers
    for this strategy's separate cash account (account_size wasn't
    reaching best_params before). POST-FIX RESULT: DEAD. At a safe
    risk_pct (widened up to 5%, nowhere near the originally-proposed
    20%), it lost money consistently in-sample and out-of-sample across
    multiple sweep_lookback_4h settings; the one candidate that looked
    good (PF ~22) was built on 6 trades and produced zero trades in the
    entire ~9-month out-of-sample window - small-sample noise, not
    signal. Not re-run by main() anymore - would need a genuinely
    different rule set to revisit, not more grid search on this one.
  - "ut_bot": ATR trailing-stop stop-and-reverse - faithful port of the
    public "UT Bot Alerts" Pine indicator (fully mechanical, no
    discretionary judgment calls, unlike liquidity_sweep's ICT-adjacent
    design). Entries AND exits both driven by the same signal (price
    crossing the trailing stop flips the position) - no separate fixed
    stop-loss, the reversal itself is the risk control. Tradeify PROP
    account this time (corrected after an initial mix-up), NOT the
    separate $2,000 cash account liquidity_sweep used - 2% risk per
    trade is against the confirmed $2,000 EOD trailing drawdown LIMIT
    (ACCOUNT_TRAILING_DRAWDOWN_LIMIT), not a capital balance, still
    $40/trade target risk by coincidence of the same number. 1-5
    contracts derived from the stop distance at entry (same
    skip-don't-force discipline liquidity_sweep needed). Requested
    sensitivity (key_value) of 2 is the default, grid-searched 1.0-3.0
    for a robustness check. Brand new, logic-verified via an engineered
    trend-reversal scenario but not yet run against real data.

MES was tested on both meanrev and vwap_pullback and dropped entirely
per user direction - real TradingView results never held up on MES the
way they did on MNQ, despite promising signals from this script's own
search on more than one occasion. MNQ only from here on.

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
    # Both off by default - extensive walk-forward testing never found
    # either filter improving results; the unfiltered baseline won every
    # time, across every symbol/timeframe tested. Still grid-searched
    # (see MEANREV_GRID) in case that changes with new data.
    use_trend_alignment=False,
    trend_len=100,
    use_obv_confirm=False,
    obv_lookback=20,
)}

MEANREV_GRID = dict(
    vwap_band_mult=[1.5, 2.0, 2.5],
    adx_threshold=[15, 20, 25],
    stop_atr_mult=[1.0, 1.5, 2.0],
    vol_mult=[1.2, 1.5],
    use_trend_alignment=[True, False],
    use_obv_confirm=[True, False],
)

VWAPPB_DEFAULTS = {**SHARED_DEFAULTS, **dict(
    adx_len=14, adx_low=20, adx_high=35,   # trending-but-not-extreme - OPPOSITE regime from meanrev
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
    # are in the grid now specifically to see whether a smaller per-trade
    # risk can hold the same edge while fitting the real risk budget.
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


def obv_series(bars):
    """On-Balance Volume - cumulative volume added on up closes, subtracted
    on down closes. Used as a volume-backed trend confirmation, separate
    from price alone (does the volume actually support the trend?)."""
    out = [0.0]
    obv = 0.0
    for i in range(1, len(bars)):
        if bars[i]["close"] > bars[i - 1]["close"]:
            obv += bars[i]["volume"]
        elif bars[i]["close"] < bars[i - 1]["close"]:
            obv -= bars[i]["volume"]
        out.append(obv)
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


def resample_bars(bars, group_size):
    """
    Groups every `group_size` CONSECUTIVE bars into one larger bar - used
    to build 4-hour bars from 60-minute ones (Yahoo has no native 4h
    interval). NOT calendar-anchored (a 4h group doesn't necessarily start
    at 00:00/04:00/08:00 UTC) - just non-overlapping consecutive chunks.
    Good enough for a research tool; a real TradingView 4h chart would be
    clock-aligned, which is one more reason this needs real confirmation
    before being trusted, same as everything else here.

    Returns (resampled_bars, end_indices) where end_indices[k] is the
    index in the ORIGINAL `bars` list of the last bar included in
    resampled_bars[k] - this is what lets the caller know exactly which
    original-timeframe bar a resampled bar's information first becomes
    knowable at (no earlier - avoiding lookahead bias is the whole point
    of tracking this).
    """
    resampled = []
    end_indices = []
    for start in range(0, len(bars) - group_size + 1, group_size):
        group = bars[start:start + group_size]
        resampled.append({
            "dt": group[0]["dt"],
            "open": group[0]["open"],
            "high": max(b["high"] for b in group),
            "low": min(b["low"] for b in group),
            "close": group[-1]["close"],
            "volume": sum(b["volume"] for b in group),
        })
        end_indices.append(start + group_size - 1)
    return resampled, end_indices


def rolling_high_low(values_high, values_low, lookback):
    """
    For each index i, the max/min over the `lookback` bars BEFORE i
    (excluding i itself) - None until enough history exists. Excluding
    the current bar is what makes this safe to compare bar i's own
    high/low against without leaking bar i's own extreme into its own
    reference level.
    """
    n = len(values_high)
    highs = [None] * n
    lows = [None] * n
    for i in range(n):
        if i >= lookback:
            highs[i] = max(values_high[i - lookback:i])
            lows[i] = min(values_low[i - lookback:i])
    return highs, lows


# ---------------------------------------------------------------------
# Shared position management (scale in/out, stops, targets) - identical
# mechanics for both strategies, only the ENTRY trigger differs.
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
        max_drawdown=_max_drawdown(trade_cashflows),
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
    obv = obv_series(bars)

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
        if p["use_obv_confirm"] and i < p["obv_lookback"]:
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

        # OBV confirmation: is real volume actually backing that trend
        # direction, not just price drifting on light volume?
        obv_rising = obv[i] > obv[i - p["obv_lookback"]]
        obv_falling = obv[i] < obv[i - p["obv_lookback"]]
        long_obv_ok = (not p["use_obv_confirm"]) or obv_rising
        short_obv_ok = (not p["use_obv_confirm"]) or obv_falling

        long_trend_ok = long_trend_ok and long_obv_ok
        short_trend_ok = short_trend_ok and short_obv_ok

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
        max_drawdown=_max_drawdown(trade_cashflows),
    )


# ---------------------------------------------------------------------
# Strategy 4: VWAP pullback trend-continuation
#
# Opposite regime from meanrev (moderately trending, ADX 20-35, not
# range-bound) and opposite direction (trades WITH the trend, entering
# on pullbacks TO VWAP that hold, not fades of extremes away from it).
# Two-stage signal: a "rejection candle" (touches VWAP, closes back on
# the trend side) sets up a pending breakout level; a later bar breaking
# that level triggers the actual entry. Reuses _simulate's shared
# scale-in/out/stop/target engine via a stateful entry_signal closure.
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


SCALP_DEFAULTS = dict(
    ema_len=9, vol_len=20, vol_mult=1.5,
    target_points=30.0, stop_points=12.0,
    size=2,
    session_start=(9, 30), session_end=(16, 0),
    commission_per_contract=1.0,
    slippage_ticks=2,
)

# Widened from the original 8-15pt target range (CONFIRMED DEAD on real
# TradingView data - PF 1.067, win rate 34.69%, barely above the 33.3%
# mathematical breakeven for its own 2:1 target:stop - see docstring
# above) to 20-40pt per a request for a "quick move" scalp with a real
# momentum-scale target instead of a noise-scale one. Same entry trigger
# (fresh VWAP cross + EMA momentum + volume spike) - this tests whether
# THAT signal works better at a bigger target, not a different signal.
SCALP_GRID = dict(
    target_points=[20.0, 25.0, 30.0, 35.0, 40.0],
    stop_points=[8.0, 10.0, 12.0, 15.0, 20.0],
    ema_len=[5, 9, 13],
    vol_mult=[1.2, 1.5, 2.0],
)


# ---------------------------------------------------------------------
# Strategy 5: Quick scalp - fixed point target/stop, auto-close, no
# scale-in/out (in and out fast, not a position to manage over time).
#
# FIRST DRAFT - not yet walk-forward tested, unlike the other strategies
# when they were first added. Entry: a fresh VWAP cross (not an extended
# one - crossing THIS bar) that closes on the fast-EMA-confirmed momentum
# side, with a volume spike. Exit: fixed point target or fixed point stop,
# whichever hits first - no ATR, no scaling, no partials, since the whole
# point is fast in/out, not a managed multi-bar position.
#
# Cost check worth keeping in mind before trusting any result here: MNQ is
# $2/point. A 10-12 point target is $20-24/contract gross before costs -
# commission ($1/side = $2 round trip) and 2-tick slippage each way (2 *
# 0.25 * 2 = $2 round trip in point terms is $1, so ~$2 in $ terms at
# $2/point) eat a real percentage of a target this small. Small targets
# need either a high win rate or a real cost edge to survive - don't
# assume this works just because the OOS number says PF > 1 on a handful
# of trades; the events count matters more here than almost anywhere else.
# ---------------------------------------------------------------------
def run_backtest_scalp(bars, symbol, params):
    p = {**SCALP_DEFAULTS, **params}
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    vwap = vwap_series(bars)
    fast_ema = ema_series(closes, p["ema_len"])
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
        if vwap[i] is None or vwap[i - 1] is None or fast_ema[i] is None or avg_vol[i] is None:
            continue

        dt = bars[i]["dt"]
        price = closes[i]
        vol_confirmed = volumes[i] > avg_vol[i] * p["vol_mult"]
        can_trade = _in_session(dt, p["session_start"], p["session_end"])

        if position is not None:
            direction = position["direction"]
            hit_target = (direction == "long" and price >= position["target"]) or \
                         (direction == "short" and price <= position["target"])
            hit_stop = (direction == "long" and price <= position["stop"]) or \
                       (direction == "short" and price >= position["stop"])
            if hit_target or hit_stop:
                close_qty(direction, position["size"], price, position["avg_entry"])
                position = None
            continue

        if not can_trade:
            continue

        fresh_cross_up = closes[i - 1] <= vwap[i - 1] and price > vwap[i] and price > fast_ema[i]
        fresh_cross_down = closes[i - 1] >= vwap[i - 1] and price < vwap[i] and price < fast_ema[i]

        if fresh_cross_up and vol_confirmed:
            fill_price = price + slippage_price
            position = dict(direction="long", size=p["size"], avg_entry=fill_price,
                             target=price + p["target_points"], stop=price - p["stop_points"])
            trade_cashflows.append(-p["commission_per_contract"] * p["size"])
        elif fresh_cross_down and vol_confirmed:
            fill_price = price - slippage_price
            position = dict(direction="short", size=p["size"], avg_entry=fill_price,
                             target=price - p["target_points"], stop=price + p["stop_points"])
            trade_cashflows.append(-p["commission_per_contract"] * p["size"])

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


LIQSWEEP_DEFAULTS = dict(
    sweep_lookback_4h=20,       # 4h liquidity pool = rolling N-bar high/low (~20 bars = ~3.3 days on 4h)
    confirm_lookback_1h=20,     # 1h break-of-structure level = rolling N-bar high/low
    confirm_window_1h=12,       # bars to wait for the 1h confirmation after a 4h sweep before giving up
    stop_buffer_points=10.0,    # stop placed beyond the swept extreme, and how far behind trailing structure
    account_size=2000.0,        # the CASH account this was designed for - separate from the Tradeify prop
                                 # account and its $2,000 trailing drawdown limit, same number, different thing
    risk_pct=0.01,              # 1% of account risked per trade (NOT the originally-proposed 20% - see docstring)
    min_contracts=1, max_contracts=5,
    commission_per_contract=1.0,
    slippage_ticks=2,
)

LIQSWEEP_GRID = dict(
    sweep_lookback_4h=[10, 20, 30],
    confirm_lookback_1h=[10, 20, 30],
    confirm_window_1h=[6, 12, 24],
    stop_buffer_points=[5.0, 10.0, 20.0],
    # Widened after the first real run showed EVERY signal being skipped
    # at 1-2% risk - MNQ's typical 4h/1h swing stop distance is simply
    # wider than a $20-40 budget affords for even 1 contract. Capped at
    # 5% (still far below the originally-proposed 20%) to find where this
    # actually becomes tradeable, not to quietly drift back toward unsafe
    # sizing - if even 5% doesn't produce a real sample, that's a real
    # finding about this instrument/account-size combination, not a
    # reason to widen further.
    risk_pct=[0.01, 0.015, 0.02, 0.03, 0.05],
    # Singleton (not actually swept) - exists only so account_size shows up
    # in best_params/grid results, which is what lets run_for()'s report
    # recognize this strategy sizes off its OWN account instead of falling
    # through to the (wrong, prop-account) drawdown budget message.
    account_size=[LIQSWEEP_DEFAULTS["account_size"]],
)


# ---------------------------------------------------------------------
# Strategy 6: Liquidity sweep swing trade (multi-timeframe confluence)
#
# 4h structure (built by resampling 60-minute bars) for the setup, 1h for
# the entry trigger. A "sweep" is a 4h bar whose high/low exceeds the
# recent rolling extreme AND closes back inside it (rejection) - the
# same rejection-then-breakout shape vwap_pullback uses, just applied to
# a rolling price extreme instead of VWAP, and to 4h structure confirmed
# on 1h instead of same-timeframe. No fixed take-profit: once filled, the
# stop trails to newly-formed 1h structure in the trade's favor instead
# of a price target. Position size is DERIVED from the stop distance to
# target a fixed risk_pct of the account, clamped to 1-5 contracts - not
# a fixed size like the other strategies here.
# ---------------------------------------------------------------------
def run_backtest_liquidity_sweep(bars_1h, symbol, params):
    p = {**LIQSWEEP_DEFAULTS, **params}
    bars_4h, end_indices_4h = resample_bars(bars_1h, 4)

    highs_4h = [b["high"] for b in bars_4h]
    lows_4h = [b["low"] for b in bars_4h]
    closes_4h = [b["close"] for b in bars_4h]
    roll_high_4h, roll_low_4h = rolling_high_low(highs_4h, lows_4h, p["sweep_lookback_4h"])

    highs_1h = [b["high"] for b in bars_1h]
    lows_1h = [b["low"] for b in bars_1h]
    closes_1h = [b["close"] for b in bars_1h]
    roll_high_1h, roll_low_1h = rolling_high_low(highs_1h, lows_1h, p["confirm_lookback_1h"])

    # Which 1h bar index each 4h sweep signal FIRST becomes knowable at -
    # the bar right after the 4h bar that produced it closes.
    trigger_at_1h_idx = {}
    for k, end_idx in enumerate(end_indices_4h):
        if roll_high_4h[k] is None:
            continue
        if highs_4h[k] > roll_high_4h[k] and closes_4h[k] < roll_high_4h[k]:
            trigger_at_1h_idx.setdefault(end_idx, []).append(("short", highs_4h[k]))
        if lows_4h[k] < roll_low_4h[k] and closes_4h[k] > roll_low_4h[k]:
            trigger_at_1h_idx.setdefault(end_idx, []).append(("long", lows_4h[k]))

    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]
    risk_dollars = p["account_size"] * p["risk_pct"]

    position = None
    trade_cashflows = []
    signals_total = 0
    signals_skipped = 0
    skipped_stop_distance_sum = 0.0

    def close_position(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    pending = {"direction": None, "sweep_extreme": None, "bars_left": 0}

    for i in range(1, len(bars_1h)):
        price = closes_1h[i]

        if (i - 1) in trigger_at_1h_idx and pending["direction"] is None and position is None:
            direction, extreme = trigger_at_1h_idx[i - 1][-1]
            pending["direction"] = direction
            pending["sweep_extreme"] = extreme
            pending["bars_left"] = p["confirm_window_1h"]

        if position is not None:
            direction = position["direction"]
            stop_hit = (direction == "long" and price <= position["stop"]) or \
                       (direction == "short" and price >= position["stop"])
            if stop_hit:
                close_position(direction, position["size"], price, position["avg_entry"])
                position = None
                continue
            if direction == "long" and roll_low_1h[i] is not None:
                new_stop = roll_low_1h[i] - p["stop_buffer_points"]
                if new_stop > position["stop"]:
                    position["stop"] = new_stop
            elif direction == "short" and roll_high_1h[i] is not None:
                new_stop = roll_high_1h[i] + p["stop_buffer_points"]
                if new_stop < position["stop"]:
                    position["stop"] = new_stop
            continue

        if pending["direction"] == "long":
            if roll_high_1h[i] is not None and closes_1h[i] > roll_high_1h[i]:
                entry_price = price
                stop_price = pending["sweep_extreme"] - p["stop_buffer_points"]
                stop_distance = entry_price - stop_price
                if stop_distance > 0:
                    signals_total += 1
                    raw_contracts = risk_dollars / (stop_distance * point_value)
                    # Skip the trade (don't force a floor of min_contracts)
                    # when the stop is too wide for even 1 contract to fit
                    # the risk budget - forcing a minimum position here is
                    # exactly what silently risks far more than risk_pct
                    # intends on the widest, least-certain stops.
                    if raw_contracts >= p["min_contracts"]:
                        qty = min(p["max_contracts"], int(raw_contracts))
                        fill_price = entry_price + slippage_price
                        position = dict(direction="long", size=qty, avg_entry=fill_price, stop=stop_price)
                        trade_cashflows.append(-p["commission_per_contract"] * qty)
                    else:
                        signals_skipped += 1
                        skipped_stop_distance_sum += stop_distance
                pending["direction"] = None
            else:
                pending["bars_left"] -= 1
                if pending["bars_left"] <= 0:
                    pending["direction"] = None
        elif pending["direction"] == "short":
            if roll_low_1h[i] is not None and closes_1h[i] < roll_low_1h[i]:
                entry_price = price
                stop_price = pending["sweep_extreme"] + p["stop_buffer_points"]
                stop_distance = stop_price - entry_price
                if stop_distance > 0:
                    signals_total += 1
                    raw_contracts = risk_dollars / (stop_distance * point_value)
                    if raw_contracts >= p["min_contracts"]:
                        qty = min(p["max_contracts"], int(raw_contracts))
                        fill_price = entry_price - slippage_price
                        position = dict(direction="short", size=qty, avg_entry=fill_price, stop=stop_price)
                        trade_cashflows.append(-p["commission_per_contract"] * qty)
                    else:
                        signals_skipped += 1
                        skipped_stop_distance_sum += stop_distance
                pending["direction"] = None
            else:
                pending["bars_left"] -= 1
                if pending["bars_left"] <= 0:
                    pending["direction"] = None

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
        signals_total=signals_total,
        signals_skipped=signals_skipped,
        avg_skipped_stop_distance=(skipped_stop_distance_sum / signals_skipped) if signals_skipped else 0.0,
    )


UTBOT_DEFAULTS = dict(
    key_value=2.0, atr_period=10,
    # Tradeify prop account, NOT the separate $2,000 cash account -
    # sizing keys off the confirmed $2,000 EOD trailing drawdown LIMIT
    # (ACCOUNT_TRAILING_DRAWDOWN_LIMIT, same constant vwap_pullback/
    # meanrev use), not a total-capital balance. 2% of that limit = $40
    # target risk per trade - same number liquidity_sweep's cash-account
    # version used, different meaning (that was 2% of the total account;
    # this is 2% of the max-tolerable-loss rule).
    risk_pct=0.02,
    min_contracts=1, max_contracts=5,
    session_start=(9, 30), session_end=(16, 0),
    commission_per_contract=1.0,
    slippage_ticks=2,
)

# key_value swept around the requested sensitivity of 2 for a robustness
# check (same reason every other strategy here gets neighborhood-tested,
# not just the single requested value) - risk_pct is a singleton (not
# actually swept) so it shows up in best_params for the report. No
# account_size here (unlike LIQSWEEP_GRID) - this strategy uses the
# module-level ACCOUNT_TRAILING_DRAWDOWN_LIMIT constant directly, so
# run_for()'s report correctly falls through to the Tradeify prop
# account budget check instead of the cash-account one.
UTBOT_GRID = dict(
    key_value=[1.0, 1.5, 2.0, 2.5, 3.0],
    atr_period=[10, 14, 20],
    risk_pct=[UTBOT_DEFAULTS["risk_pct"]],
)


# ---------------------------------------------------------------------
# Strategy 7: UT Bot Alerts - ATR trailing-stop stop-and-reverse
#
# Faithful port of the well-known public "UT Bot Alerts" Pine indicator
# (Kivanc Ozbilgic) - fully mechanical, no discretionary judgment calls
# to approximate (unlike liquidity_sweep's ICT-adjacent design), so this
# translation should track the real Pine behavior closely. An ATR-based
# trailing stop line only ever tightens in the position's favor; price
# crossing it flips the position (stop-and-reverse - always long or
# short once the first signal fires, never flat by design, same as the
# original). Entries AND exits are both driven purely by that same
# signal, per request - there is no separate fixed stop-loss layered on
# top; the reversal itself is the risk control.
#
# Position size is DERIVED from the stop distance at the moment of entry
# (which works out to key_value * ATR, the same distance the trailing
# stop was placed at) to target a fixed risk_pct of the $2,000 cash
# account, clamped 1-5 contracts - same discipline as liquidity_sweep:
# a trade is SKIPPED, not forced to 1 contract, when even 1 contract
# would risk more than the budget.
# ---------------------------------------------------------------------
def run_backtest_ut_bot(bars, symbol, params):
    p = {**UTBOT_DEFAULTS, **params}
    closes = [b["close"] for b in bars]
    atr = atr_series(bars, p["atr_period"])

    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]
    # Tradeify prop account: risk_pct applies against the confirmed
    # $2,000 EOD trailing drawdown LIMIT, not a cash balance.
    risk_dollars = ACCOUNT_TRAILING_DRAWDOWN_LIMIT * p["risk_pct"]

    position = None
    trade_cashflows = []
    signals_total = 0
    signals_skipped = 0
    skipped_stop_distance_sum = 0.0

    def close_position(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    prev_stop = 0.0
    prev_src = closes[0]

    for i in range(1, len(bars)):
        if atr[i] is None:
            prev_src = closes[i]
            continue

        src = closes[i]
        n_loss = p["key_value"] * atr[i]

        # Faithful port of xATRTrailingStop's three-branch update - only
        # ever tightens toward price in the held direction, never loosens.
        if src > prev_stop and prev_src > prev_stop:
            new_stop = max(prev_stop, src - n_loss)
        elif src < prev_stop and prev_src < prev_stop:
            new_stop = min(prev_stop, src + n_loss)
        elif src > prev_stop:
            new_stop = src - n_loss
        else:
            new_stop = src + n_loss

        # ema(src, 1) == src exactly (smoothing factor 1), so this is
        # crossover(src, stop) / crossover(stop, src) directly.
        above = src > new_stop and prev_src <= prev_stop
        below = new_stop > src and prev_stop <= prev_src
        buy_signal = src > new_stop and above
        sell_signal = src < new_stop and below

        can_trade = _in_session(bars[i]["dt"], p["session_start"], p["session_end"])

        if can_trade and buy_signal:
            signals_total += 1
            if position is not None and position["direction"] == "short":
                close_position("short", position["size"], src, position["avg_entry"])
                position = None
            if position is None:
                stop_distance = abs(src - new_stop)
                if stop_distance > 0:
                    raw_contracts = risk_dollars / (stop_distance * point_value)
                    if raw_contracts >= p["min_contracts"]:
                        qty = min(p["max_contracts"], int(raw_contracts))
                        fill_price = src + slippage_price
                        position = dict(direction="long", size=qty, avg_entry=fill_price)
                        trade_cashflows.append(-p["commission_per_contract"] * qty)
                    else:
                        signals_skipped += 1
                        skipped_stop_distance_sum += stop_distance
        elif can_trade and sell_signal:
            signals_total += 1
            if position is not None and position["direction"] == "long":
                close_position("long", position["size"], src, position["avg_entry"])
                position = None
            if position is None:
                stop_distance = abs(new_stop - src)
                if stop_distance > 0:
                    raw_contracts = risk_dollars / (stop_distance * point_value)
                    if raw_contracts >= p["min_contracts"]:
                        qty = min(p["max_contracts"], int(raw_contracts))
                        fill_price = src - slippage_price
                        position = dict(direction="short", size=qty, avg_entry=fill_price)
                        trade_cashflows.append(-p["commission_per_contract"] * qty)
                    else:
                        signals_skipped += 1
                        skipped_stop_distance_sum += stop_distance

        prev_stop = new_stop
        prev_src = src

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
        signals_total=signals_total,
        signals_skipped=signals_skipped,
        avg_skipped_stop_distance=(skipped_stop_distance_sum / signals_skipped) if signals_skipped else 0.0,
    )


STRATEGIES = {
    "crossover": dict(run=run_backtest_crossover, grid=CROSSOVER_GRID, group_by=("fast_len", "slow_len")),
    "orb": dict(run=run_backtest_orb, grid=ORB_GRID, group_by=("adx_threshold",)),
    "meanrev": dict(run=run_backtest_meanrev, grid=MEANREV_GRID, group_by=("use_trend_alignment", "use_obv_confirm")),
    "vwap_pullback": dict(run=run_backtest_vwap_pullback, grid=VWAPPB_GRID, group_by=("adx_low", "adx_high")),
    "ut_bot": dict(run=run_backtest_ut_bot, grid=UTBOT_GRID, group_by=("key_value",)),
    "scalp": dict(run=run_backtest_scalp, grid=SCALP_GRID, group_by=("target_points", "stop_points")),
    "liquidity_sweep": dict(run=run_backtest_liquidity_sweep, grid=LIQSWEEP_GRID,
                             group_by=("sweep_lookback_4h", "confirm_lookback_1h")),
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
        # If the strategy tracks signal/sizing diagnostics (currently just
        # liquidity_sweep), show them even here - "no trades" can mean "no
        # setups happened" or "setups happened but all got sized out,"
        # which need very different fixes, and the normal report path
        # never reaches per-combo output when top is empty.
        diag = strat["run"](in_sample, symbol, {})
        if diag.get("signals_total") is not None:
            print(f"  Diagnostic (default params, full in-sample): "
                  f"signals_total={diag['signals_total']}  "
                  f"signals_skipped_undersized={diag['signals_skipped']}  "
                  f"avg_skipped_stop_distance={diag['avg_skipped_stop_distance']:.1f} points")
            if diag['signals_total'] and diag['signals_skipped'] == diag['signals_total']:
                print("  -> EVERY signal was skipped for being too large to size at the "
                      "current risk_pct - the risk budget is too tight for this "
                      "instrument/timeframe's typical stop distance, not a lack of setups.")
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

        # Strategies that size off their OWN account (e.g. liquidity_sweep's
        # separate $2,000 CASH account, which has no external trailing-
        # drawdown rule like the prop account does - just personal risk
        # tolerance) get their own budget instead of the prop account's.
        if "account_size" in best_params:
            budget_limit = best_params["account_size"]
            budget_safety = budget_limit * 0.15
            budget_note = f"15% of the ${budget_limit:.0f} cash account (a default assumption, not an external rule - adjust to your own risk tolerance)"
        else:
            budget_limit = ACCOUNT_TRAILING_DRAWDOWN_LIMIT
            budget_safety = DRAWDOWN_SAFETY_BUDGET
            budget_note = f"real account trailing drawdown limit: ${budget_limit:.0f}"

        if oos_stats["max_drawdown"] > budget_safety:
            print(f"      !! max_drawdown ${oos_stats['max_drawdown']:.2f} exceeds the "
                  f"${budget_safety:.0f} safety budget ({budget_note}).")
            if "base_size" in best_params and "max_size" in best_params:
                sug_base, sug_max = suggest_size_for_budget(
                    oos_stats["max_drawdown"], best_params["base_size"], best_params["max_size"])
                print(f"      -> Rough linear-scaling suggestion: base_size={sug_base}, "
                      f"max_size={sug_max} (was {best_params['base_size']}/{best_params['max_size']}). "
                      f"RE-RUN at this size to confirm, don't just trust the scaling math - "
                      f"stop-loss noise doesn't scale perfectly linearly in practice.")
            elif "size" in best_params:
                sug_size = max(1, round(best_params["size"] * budget_safety / oos_stats["max_drawdown"]))
                print(f"      -> Rough linear-scaling suggestion: size={sug_size} "
                      f"(was {best_params['size']}). RE-RUN at this size to confirm.")
            elif "risk_pct" in best_params:
                sug_risk_pct = best_params["risk_pct"] * budget_safety / oos_stats["max_drawdown"]
                print(f"      -> This strategy sizes FROM risk_pct already (not a fixed "
                      f"contract count) - try risk_pct={sug_risk_pct:.4f} (was "
                      f"{best_params['risk_pct']}) and re-run to confirm.")


def main():
    # MES dropped entirely per real TradingView results (meanrev held up on
    # MNQ 5m, did not hold up on MES 5m) - MNQ only from here on.
    #
    # vwap_pullback: tighter stops (down to 0.5x ATR) were tested and
    # confirmed to NOT work (OOS PF 0.000) - the original 1.5x ATR/
    # ADX 15-30 config keeps holding up instead across re-runs (latest:
    # PF 1.087, 27 trades, $1,201.50 max drawdown - now under the $1,300
    # safety budget at default 3/3/9 sizing on this window). Still
    # running both 5m/15m each time to keep confirming that holds as new
    # data comes in. 15m has no real edge (PF ~1.05 on real TradingView
    # data) - kept only as a comparison, not expected to improve.
    for interval in ["5m", "15m"]:
        run_for("MNQ=F", interval, "vwap_pullback")

    # scalp: DEAD at both the original 8-15pt target AND the widened
    # 20-40pt "quick move" target - see docstring above. Not re-running
    # it here; the fresh-VWAP-cross entry trigger itself doesn't have
    # real edge at either scale.

    # liquidity_sweep: real data (after fixing two sizing bugs - see
    # docstring above) came back a consistent net LOSER in-sample and
    # out-of-sample across multiple settings at a safe risk_pct (up to
    # 5%) - DEAD as designed, not re-running it here. Would need a
    # genuinely different rule set to revisit, not more grid search.

    # ut_bot: brand new, first walk-forward pass. Requested sensitivity
    # (key_value=2) plus a robustness sweep either side of it (1.0-3.0).
    # Tradeify prop account (corrected from an initial cash-account
    # mix-up) - 2% risk against the $2,000 trailing drawdown limit.
    run_for("MNQ=F", "5m", "ut_bot")


if __name__ == "__main__":
    main()
