"""
Opening Range Breakout + VWAP retest - THEORETICAL, SIDE RESEARCH ONLY.

NOT the confirmed strategy. This is a separate idea being worked through in
parallel with (never instead of) vwap_pullback, which is what
backtest_optimizer.py validates and what's actually running the live paper
trading test right now. Kept in its own file on purpose so it can never get
mixed into or accidentally affect that confirmed tool - only a few low-level
helpers (data fetch, VWAP, shared account risk constants) are imported from
it, no strategy logic.

Idea, based on LuxAlgo's "Opening Range with Breakouts & Targets" indicator
(pinescript/ - source pasted by the user; that script itself is a pure
visualization tool with no position management of its own, so all of the
entry/stop/target rules below were designed fresh, using its opening-range
math as the foundation):

  1. Opening range = the high/low of the first 15 minutes of the session,
     09:30:00-09:44:59 ET.
  2. After the range closes, watch for a breakout close above the OR high
     (arms a LONG bias) or below the OR low (arms a SHORT bias).
  3. Wait for price to pull back and RETEST the broken level - a bar's low
     reaching back down to the OR high (for a long) or a bar's high reaching
     back up to the OR low (for a short) - while price is on the
     corresponding side of VWAP (above VWAP for the long retest, below for
     the short). That retest, not the initial breakout, is the entry.
  4. Stop-loss: a flat 25 points from the entry fill, regardless of how wide
     that day's opening range was.
  5. Targets: reuse the LuxAlgo indicator's own extension ladder (OR width x
     50% per level) - T1 = entry side +/- 0.5x OR width, T2 = +/- 1.0x OR
     width.
  6. Sizing/exits, at the same 2-contract size vwap_pullback is currently
     confirmed at: 1 contract (50%) closed at T1, stop moved to breakeven on
     the remainder, second contract closed at T2 (flat).

Two design choices were made without an explicit answer (asked twice,
answered with "just get the variables set" - proceeding on reasonable
defaults, flagged here so they're easy to correct):
  - Retest tolerance: a bar's own completed high/low reaching the OR level
    counts as a touch - no extra tolerance band. This is checked using that
    bar's high/low (known only once the bar has closed - not a lookahead),
    while the stop check uses close only, matching backtest_optimizer.py's
    convention there.
  - Bias arm/reset: a breakout arms a bias; it's consumed by the retest
    entry, or cancelled if price closes back through the OR midpoint before
    a retest happens; either way a fresh breakout re-arms it. Mirrors the
    LuxAlgo source's own up_check/down_check logic.
  - Positions and armed biases are flattened/reset at the start of each new
    session day - the opening range is inherently a daily construct, so
    nothing carries overnight in this model (unlike vwap_pullback, which
    doesn't force an end-of-day flatten).

UNTESTED AS OF THIS BUILD. Nothing here has been walk-forward grid-searched,
robustness-scored, or confirmed in TradingView - it's a single fixed rule
set, checked in-sample vs out-of-sample once. Treat "held up out-of-sample"
as "worth a closer look," not as edge.

Run locally (needs normal internet access - this cannot run inside the
sandboxed session that built it):

    python research_orb_retest.py
"""

from backtest_optimizer import (
    fetch_bars, split_in_out_sample, vwap_series,
    POINT_VALUE, TICK_SIZE, ACCOUNT_TRAILING_DRAWDOWN_LIMIT, DRAWDOWN_SAFETY_BUDGET,
    _max_drawdown,
)

OR_START = (9, 30)
OR_END_EXCLUSIVE = (9, 45)   # OR window is [9:30, 9:45) ET
SESSION_END = (16, 0)

ORB_DEFAULTS = dict(
    stop_points=25.0,
    target1_or_mult=0.5,
    target2_or_mult=1.0,
    base_size=2,
    commission_per_contract=1.0,
    slippage_ticks=2,
)


def _time_tuple(dt):
    return (dt.hour, dt.minute)


def compute_daily_or(bars):
    """{date: {orh, orl, orm, orw}} from each session's 09:30-09:44 ET bars."""
    daily = {}
    for b in bars:
        t = _time_tuple(b["dt"])
        if OR_START <= t < OR_END_EXCLUSIVE:
            day = b["dt"].date()
            entry = daily.setdefault(day, {"orh": b["high"], "orl": b["low"]})
            entry["orh"] = max(entry["orh"], b["high"])
            entry["orl"] = min(entry["orl"], b["low"])
    out = {}
    for day, v in daily.items():
        orh, orl = v["orh"], v["orl"]
        out[day] = dict(orh=orh, orl=orl, orm=(orh + orl) / 2, orw=orh - orl)
    return out


def run_backtest_orb_retest(bars, symbol, params):
    p = {**ORB_DEFAULTS, **params}
    daily_or = compute_daily_or(bars)
    return _run_indexed(bars, symbol, p, daily_or)


def _run_indexed(bars, symbol, p, daily_or):
    vwap = vwap_series(bars)
    point_value = POINT_VALUE[symbol]
    slippage_price = TICK_SIZE[symbol] * p["slippage_ticks"]

    position = None
    trade_cashflows = []

    def close_qty(direction, qty, price, avg_entry):
        fill_price = price - slippage_price if direction == "long" else price + slippage_price
        per_contract = (fill_price - avg_entry) if direction == "long" else (avg_entry - fill_price)
        trade_cashflows.append(per_contract * point_value * qty - p["commission_per_contract"] * qty)

    long_armed = short_armed = False
    current_day = None
    orh = orl = orm = orw = None

    for i, b in enumerate(bars):
        day = b["dt"].date()
        t = _time_tuple(b["dt"])

        if day != current_day:
            current_day = day
            long_armed = short_armed = False
            position = None
            day_or = daily_or.get(day)
            orh = day_or["orh"] if day_or else None
            orl = day_or["orl"] if day_or else None
            orm = day_or["orm"] if day_or else None
            orw = day_or["orw"] if day_or else None

        if orh is None or not orw or vwap[i] is None:
            continue
        if t < OR_END_EXCLUSIVE or t > SESSION_END:
            continue

        price = b["close"]

        if position is not None:
            direction = position["direction"]
            stop_hit = (direction == "long" and price <= position["stop"]) or \
                       (direction == "short" and price >= position["stop"])
            if stop_hit:
                close_qty(direction, position["size"], price, position["avg_entry"])
                position = None
                continue

            t1, t2 = position["t1"], position["t2"]
            hit_t1 = (direction == "long" and b["high"] >= t1) or (direction == "short" and b["low"] <= t1)
            hit_t2 = (direction == "long" and b["high"] >= t2) or (direction == "short" and b["low"] <= t2)

            if hit_t2 and not position["t2_hit"]:
                close_qty(direction, position["size"], t2, position["avg_entry"])
                position = None
                continue
            elif hit_t1 and not position["t1_hit"] and position["size"] > 1:
                trim = position["size"] // 2
                close_qty(direction, trim, t1, position["avg_entry"])
                position["size"] -= trim
                position["t1_hit"] = True
                position["stop"] = position["avg_entry"]  # move to breakeven
                continue
            continue

        if not long_armed and price > orh:
            long_armed = True
        if price < orm:
            long_armed = False
        if not short_armed and price < orl:
            short_armed = True
        if price > orm:
            short_armed = False

        if long_armed and b["low"] <= orh and price > vwap[i]:
            fill_price = price + slippage_price
            position = dict(direction="long", size=p["base_size"], avg_entry=fill_price,
                             stop=fill_price - p["stop_points"],
                             t1=orh + orw * p["target1_or_mult"], t2=orh + orw * p["target2_or_mult"],
                             t1_hit=False, t2_hit=False)
            trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])
            long_armed = False
        elif short_armed and b["high"] >= orl and price < vwap[i]:
            fill_price = price - slippage_price
            position = dict(direction="short", size=p["base_size"], avg_entry=fill_price,
                             stop=fill_price + p["stop_points"],
                             t1=orl - orw * p["target1_or_mult"], t2=orl - orw * p["target2_or_mult"],
                             t1_hit=False, t2_hit=False)
            trade_cashflows.append(-p["commission_per_contract"] * p["base_size"])
            short_armed = False

    gross_profit = sum(c for c in trade_cashflows if c > 0)
    gross_loss = -sum(c for c in trade_cashflows if c < 0)
    net = sum(trade_cashflows)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    return dict(
        events=len(trade_cashflows), net_pnl=net,
        gross_profit=gross_profit, gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown=_max_drawdown(trade_cashflows),
    )


def run_for(symbol="MNQ=F", interval="5m"):
    print(f"\n{'=' * 70}\nORB RETEST (theoretical/side research)  |  {symbol}  |  {interval}\n{'=' * 70}")
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
    daily_or_in = compute_daily_or(in_sample)
    daily_or_out = compute_daily_or(out_sample)

    in_stats = _run_indexed(in_sample, symbol, ORB_DEFAULTS, daily_or_in)
    print(f"  IN-SAMPLE  ({in_sample[0]['dt'].date()} to {in_sample[-1]['dt'].date()}): "
          f"PF={in_stats['profit_factor']:.3f}  events={in_stats['events']}  "
          f"net=${in_stats['net_pnl']:.2f}  max_drawdown=${in_stats['max_drawdown']:.2f}")

    out_stats = _run_indexed(out_sample, symbol, ORB_DEFAULTS, daily_or_out)
    print(f"  OUT-OF-SAMPLE ({out_sample[0]['dt'].date()} to {out_sample[-1]['dt'].date()}): "
          f"PF={out_stats['profit_factor']:.3f}  events={out_stats['events']}  "
          f"net=${out_stats['net_pnl']:.2f}  max_drawdown=${out_stats['max_drawdown']:.2f}")

    if out_stats["profit_factor"] >= 1.0 and out_stats["events"] >= 10:
        print("  -> Held up out-of-sample with a real sample size. Worth a closer look "
              "(still not TradingView-confirmed - that's the next gate, same as always).")
    else:
        print("  -> Did not hold up, or too few trades to mean anything. Not promising as-is.")

    if out_stats["max_drawdown"] > DRAWDOWN_SAFETY_BUDGET:
        print(f"  !! max_drawdown ${out_stats['max_drawdown']:.2f} exceeds the "
              f"${DRAWDOWN_SAFETY_BUDGET:.0f} safety budget (hard account limit: "
              f"${ACCOUNT_TRAILING_DRAWDOWN_LIMIT:.0f}) at base_size={ORB_DEFAULTS['base_size']}.")


def main():
    # 5m first (60-day sample, matches vwap_pullback's data window). 1m too,
    # for the "drop to the 1-minute chart" case - but Yahoo caps 1-minute
    # data at 7 days, so treat that result as a very small, low-confidence
    # sample, not a real out-of-sample test.
    for interval in ["5m", "1m"]:
        run_for("MNQ=F", interval)


if __name__ == "__main__":
    main()
