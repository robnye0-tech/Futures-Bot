"""
Walk-forward parameter robustness search for the momentum/volume
scale-in-out strategy (mirrors pinescript/jarvis_mnq_mes_scaler.pine).

WHY THIS EXISTS: manually tweaking one parameter at a time in TradingView
and re-testing against the same window is how you accidentally overfit to
noise. This script instead:

  1. Pulls free historical MNQ/MES data (Yahoo Finance).
  2. Splits it chronologically into an IN-SAMPLE period (used for search)
     and an OUT-OF-SAMPLE period (never touched during search).
  3. Grid-searches parameters on the in-sample data only.
  4. Scores parameter combos by ROBUSTNESS (how well nearby EMA pairs
     perform on average across different stop/filter settings), not just
     whichever single combo got the highest peak number.
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
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Yahoo's own limits per interval - requesting more than this just gets
# silently clamped, so these are the real ceilings on sample size.
INTERVAL_MAX_RANGE = {
    "30m": "60d",
    "60m": "730d",
}

POINT_VALUE = {"MNQ=F": 2.0, "MES=F": 5.0}
TICK_SIZE = {"MNQ=F": 0.25, "MES=F": 0.25}

DEFAULTS = dict(
    fast_len=9, slow_len=21, atr_len=14, vol_len=20, vol_mult=1.5,
    base_size=3, add_size=3, max_size=9,
    stop_atr_mult=1.5, scale_in_atr_mult=1.0,
    target1_atr_mult=1.0, target2_atr_mult=2.0,
    use_trend_filter=True, trend_len=200,
    use_vwap_filter=True,
    session_start=(9, 30), session_end=(16, 0),
    commission_per_contract=1.0,
    slippage_ticks=2,
)

# Grid kept intentionally modest - this is about finding a robust
# neighborhood, not exhaustively searching every possible combination.
PARAM_GRID = dict(
    fast_len=[7, 9, 11],
    slow_len=[18, 21, 25],
    stop_atr_mult=[1.2, 1.5, 1.8],
    use_trend_filter=[True, False],
    use_vwap_filter=[True, False],
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


def atr_series(bars, length):
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
    out = [None] * len(trs)
    if len(trs) < length:
        return out
    atr = statistics.mean(trs[:length])
    out[length - 1] = atr
    for i in range(length, len(trs)):
        atr = (atr * (length - 1) + trs[i]) / length
        out[i] = atr
    return out


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
# Strategy simulation - mirrors the Pine Script's entry/scale/exit logic
# ---------------------------------------------------------------------
def run_backtest(bars, symbol, params):
    p = {**DEFAULTS, **params}
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    ema_fast = ema_series(closes, p["fast_len"])
    ema_slow = ema_series(closes, p["slow_len"])
    trend_ema = ema_series(closes, p["trend_len"])
    atr = atr_series(bars, p["atr_len"])
    avg_vol = sma_series(volumes, p["vol_len"])
    vwap = vwap_series(bars)

    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]

    position = None
    trade_cashflows = []  # every commission/PnL event; sums to true net PnL

    def in_session(dt):
        sh, sm = p["session_start"]
        eh, em = p["session_end"]
        t = (dt.hour, dt.minute)
        return (sh, sm) <= t <= (eh, em)

    def close_qty(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    for i in range(1, len(bars)):
        if (atr[i] is None or avg_vol[i] is None or ema_slow[i] is None
                or (p["use_trend_filter"] and trend_ema[i] is None)
                or (p["use_vwap_filter"] and vwap[i] is None)):
            continue

        dt = bars[i]["dt"]
        price = closes[i]
        vol_confirmed = volumes[i] > avg_vol[i] * p["vol_mult"]
        cross_up = ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]
        cross_down = ema_fast[i - 1] >= ema_slow[i - 1] and ema_fast[i] < ema_slow[i]

        if p["use_trend_filter"]:
            cross_up = cross_up and price > trend_ema[i]
            cross_down = cross_down and price < trend_ema[i]
        if p["use_vwap_filter"]:
            cross_up = cross_up and price > vwap[i]
            cross_down = cross_down and price < vwap[i]

        cross_up = cross_up and vol_confirmed
        cross_down = cross_down and vol_confirmed
        can_trade = in_session(dt)

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
            if cross_up:
                fill_price = price + slippage_price
                position = dict(direction="long", size=p["base_size"], avg_entry=fill_price,
                                 last_scale_price=price, stop=price - atr[i] * p["stop_atr_mult"],
                                 target1_hit=False, target2_hit=False)
                trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])
            elif cross_down:
                fill_price = price - slippage_price
                position = dict(direction="short", size=p["base_size"], avg_entry=fill_price,
                                 last_scale_price=price, stop=price + atr[i] * p["stop_atr_mult"],
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
# Grid search + robustness scoring
# ---------------------------------------------------------------------
def grid_search(bars_in_sample, symbol):
    keys = list(PARAM_GRID.keys())
    combos = list(itertools.product(*PARAM_GRID.values()))
    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        stats = run_backtest(bars_in_sample, symbol, params)
        results.append((params, stats))
    return results


def robust_candidates(results, top_n=3):
    """
    Groups results by (fast_len, slow_len) and scores each pair by the
    MEDIAN profit factor across all other param variations tested with
    that pair - a pair that's only good with one exact stop/filter combo
    is fragile; a pair that's good across most combos is more trustworthy.
    """
    by_pair = {}
    for params, stats in results:
        key = (params["fast_len"], params["slow_len"])
        by_pair.setdefault(key, []).append((params, stats))

    pair_scores = []
    for pair, entries in by_pair.items():
        pfs = [s["profit_factor"] for _, s in entries if s["events"] >= 10]
        if len(pfs) < 3:
            continue  # not enough valid samples in this pair's neighborhood
        median_pf = statistics.median(pfs)
        best_params, best_stats = max(entries, key=lambda e: e[1]["profit_factor"])
        pair_scores.append((pair, median_pf, best_params, best_stats))

    pair_scores.sort(key=lambda x: x[1], reverse=True)
    return pair_scores[:top_n]


# ---------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------
def run_for(symbol, interval):
    print(f"\n{'=' * 70}\n{symbol}  |  {interval}\n{'=' * 70}")
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

    results = grid_search(in_sample, symbol)
    top = robust_candidates(results)

    if not top:
        print("  No candidate had enough trades in-sample to evaluate. Try a longer interval.")
        return

    print("\n  Most robust (fast_len, slow_len) pairs (by median profit factor across settings):")
    for rank, (pair, median_pf, best_params, best_in_sample_stats) in enumerate(top, 1):
        print(f"\n  #{rank}: fast={pair[0]} slow={pair[1]}  "
              f"(in-sample median PF across variants: {median_pf:.3f})")
        print(f"      Best in-sample combo: {best_params}")
        print(f"      In-sample result: PF={best_in_sample_stats['profit_factor']:.3f}  "
              f"events={best_in_sample_stats['events']}  net=${best_in_sample_stats['net_pnl']:.2f}")

        # The one and only out-of-sample test for this candidate.
        oos_stats = run_backtest(out_sample, symbol, best_params)
        print(f"      OUT-OF-SAMPLE result: PF={oos_stats['profit_factor']:.3f}  "
              f"events={oos_stats['events']}  net=${oos_stats['net_pnl']:.2f}")
        if oos_stats["profit_factor"] >= 1.0:
            print("      -> Held up out-of-sample. Worth taking to TradingView for final confirmation.")
        else:
            print("      -> Did NOT hold up out-of-sample. Treat the in-sample number as noise, not edge.")


def main():
    for symbol in ["MNQ=F", "MES=F"]:
        for interval in ["30m", "60m"]:
            run_for(symbol, interval)


if __name__ == "__main__":
    main()
