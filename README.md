# Futures Bot

Momentum/volume scale-in-out trading strategy for MNQ (Micro Nasdaq) and MES
(Micro S&P 500) futures, built for a Tradeify Sim Funded account.

## Important: architecture note (read this first)

The original plan was a pure Python bot (Lumibot) connecting directly to
Tradovate's API. **That path does not work for Sim Funded prop firm
accounts** — Tradovate only issues API credentials (CID/Secret) for Live
Funded accounts. Sim Funded accounts must automate through the trading
platform itself instead.

As a result, this repo now has two parts:

1. **`pinescript/`** — the actual live trading logic, written in Pine Script
   to run on TradingView (free real-time futures data), with its alerts
   wired to [PickMyTrade](https://pickmytrade.trade/) (a webhook bridge) to
   execute on your Tradeify account. **This is the active trading path.**
2. **`strategy.py` and friends** (Python/Lumibot) — the original direct-API
   version. Left in the repo for reference and because the dashboard/news
   feed pieces are still useful, but `strategy.py` **cannot place live
   trades on a Sim Funded account** and should not be run expecting it to.

### Which Pine Script to use

- **`jarvis_meanrev_vwap_scaler.pine`** — **current candidate, MNQ only.**
  VWAP mean-reversion: fades price back toward VWAP when stretched beyond
  a volatility band, only in range-bound conditions (ADX below threshold
  — the inverse filter from ORB). **MNQ, 5-minute chart** has real
  TradingView confirmation with commission/slippage included: profit
  factor 1.185–1.403 depending on VWAP band width, ~100+ trades, tested
  on multiple real (non-overlapping-in-search) windows. **MES on the same
  setup did NOT hold up** on real data (PF 0.6–0.8) despite an earlier
  strong signal in `backtest_optimizer.py`'s search — that MES result
  didn't survive real-world confirmation. Trend-alignment and OBV
  confirmation filters exist as toggles but default **off** — extensive
  testing never found either one improving results. Commission
  ($1/contract) and slippage (2 ticks) are baked into the script itself.
- `jarvis_orb_vwap_scaler.pine` — Opening Range Breakout + VWAP + ADX
  momentum filter. Walk-forward tested across MNQ/MES 1m/5m/15m and
  failed everywhere except one MNQ 1-minute config that only held up on a
  3-day/26-trade sample (too thin to trust) — a larger TradingView sample
  on the same idea came back clearly negative. Kept for reference only.
- `jarvis_mnq_mes_scaler.pine` — EMA crossover version. Walk-forward tested
  (see `backtest_optimizer.py` and the "Open items" section) and found to
  have **no real out-of-sample edge** on MNQ/MES. Kept for reference only —
  do not use this one going forward.

- **`jarvis_vwap_pullback_mnq.pine`** — **newest candidate, MNQ only.**
  Trend-continuation (opposite mechanism from mean-reversion): trades
  WITH a moderately trending market (ADX in a band, not below a ceiling)
  on pullbacks to VWAP that get rejected and then break out in the trend
  direction. Now auto-switches its ADX band / trend EMA lengths / stop
  multiple based on the chart's timeframe (input "Auto-Adjust Parameters
  By Chart Timeframe", default on) — drop it on a 1m/5m/15m MNQ chart
  without manually changing inputs. **Real TradingView results (June
  18–Aug 12 window):**
  - **5-minute**: PF 1.527, 52 trades, $4,928 net — a real signal, but
    **$3,570 max drawdown against the account's confirmed $2,000 EOD
    trailing drawdown limit** at the tested 3/3/9 contract sizing. **Not
    tradeable at that size as-is.** `backtest_optimizer.py` now searches
    tighter stop multiples (down to 0.5x ATR) to find a config that
    holds the edge within the real risk budget — this is the current
    open item, see below.
  - **15-minute**: PF ~1.05 with the config found for that timeframe
    (ADX 20-40, EMA 10/100, stop 2.0x ATR) — essentially breakeven, no
    real edge. Entries are automatically disabled on 15-minute charts
    (and on any timeframe other than 5-minute) via a validation gate —
    the on-chart status table's "Timeframe" row shows green when entries
    are live, orange when they're disabled pending real confirmation.
  MES was dropped entirely per the same MNQ-only decision as
  mean-reversion. Commission ($1/contract) and slippage (2 ticks) are
  baked into the script.

## Active setup: Pine Script + TradingView + PickMyTrade

1. Open TradingView, load an **MNQ1!** continuous futures chart on a
   **5-minute timeframe** (the only setup with real, confirmed edge as of
   now — MES on the same setup did not hold up, see above).
2. Open Pine Editor, paste in `pinescript/jarvis_meanrev_vwap_scaler.pine`,
   and add it to the chart as a strategy.
3. Adjust the inputs in the strategy settings if needed (they mirror the
   constants that were in `config.py`) — position sizing, ATR multiples,
   session hours, and the daily kill switch dollar amount. **Confirm the
   real Tradeify max trailing drawdown figure and set the kill switch
   comfortably below it before going live.**
4. Sign up for [PickMyTrade](https://pickmytrade.trade/) and connect your
   Tradeify/Tradovate account through their dashboard.
5. In PickMyTrade's dashboard, generate the webhook URL and JSON alert
   template for your account (**do not hand-write this JSON yourself** —
   use their generator, it embeds your account token correctly).
6. In TradingView, create an alert on the strategy (condition: "Order
   fills" or "Any alert() function call", whichever PickMyTrade's current
   docs specify), paste in the webhook URL and the generated JSON template
   from step 5.
7. **Test in TradingView's Bar Replay / paper mode and against PickMyTrade's
   test/demo routing first.** Do not point a freshly-wired alert straight at
   a funded account.

## Parameter tuning: use the optimizer, don't hand-tweak in TradingView

`backtest_optimizer.py` runs a proper walk-forward parameter search
locally (needs normal internet access — Yahoo Finance is blocked in the
sandboxed environment this was built in, so this has to run on your own
machine):

```
python backtest_optimizer.py
```

What it does:
1. Pulls free historical MNQ/MES data (1-min bars: ~7 days available;
   5-min/15-min bars: ~60 days; 60-min bars: up to ~2 years — Yahoo's own
   limits, not something we can change without a paid data source).
2. Splits it chronologically: first 70% = in-sample (used for search),
   last 30% = out-of-sample (never touched during search).
3. Grid-searches a modest parameter set on in-sample data only, and scores
   candidates by how consistently they perform across different stop/filter
   settings (robust), not just whichever single combo peaked highest
   (likely overfit).
4. Takes the most robust candidate(s) and runs each ONCE, unchanged, on
   the out-of-sample data. **That out-of-sample number is the one to
   trust** — if profit factor holds above 1.0 there, it's a real signal;
   if it collapses, the in-sample result was noise.

It supports five strategy families (`crossover`, `orb`, `meanrev`,
`vwap_pullback`, `scalp` — see `STRATEGIES` dict in the script). `main()`
currently runs, MNQ only (MES dropped):
- `vwap_pullback` on 5m/15m — re-running with a widened `stop_atr_mult`
  grid (down to 0.5x ATR) to find a config that holds the real 5-minute
  edge (PF 1.527 confirmed on TradingView) within the account's real
  $2,000 drawdown budget, since the tested 3/3/9-contract config drew
  down $3,570 — see Pine Script section above and "Position sizing"
  below.
- `scalp` on 1m/5m — a new, **untested** fixed-point-target strategy
  (10-15 point target, tight stop, auto-close, no scale-in/out) for a
  quick-in-quick-out approach, as opposed to the managed multi-bar
  positions the other three strategies hold. Entry: a fresh VWAP cross
  confirmed by fast EMA momentum + a volume spike. Small targets mean
  commission+slippage eat a real percentage of the target, so treat any
  promising-looking PF here with extra skepticism until the events count
  and net PnL are checked, not just the ratio.

`meanrev`'s best result (MNQ 5m) already has real TradingView
confirmation — see the Pine Script section above — but **its max
drawdown against the real $2,000 limit has never been checked**, unlike
`vwap_pullback` (see "Position sizing" below) — this is an open item.
`crossover` and `orb` are kept only for reference; both have already
been tested and shown to lack real out-of-sample edge.

### Position sizing: size from the drawdown budget, not from margin capacity

The account allows up to 40 MNQ contracts on margin, but that number is
irrelevant to position sizing here — the account's real constraint is a
**$2,000 EOD trailing drawdown limit** (confirmed), which is a much
tighter ceiling. `_max_drawdown()` in `backtest_optimizer.py` now tracks
peak-to-trough drawdown on the closed-trade equity curve for every
strategy, and the report flags any candidate whose out-of-sample max
drawdown exceeds `DRAWDOWN_SAFETY_BUDGET` ($1,300 — a buffer below the
real $2,000 limit, not the limit itself) with a rough linear-scaling size
suggestion (`suggest_size_for_budget()`). Treat that suggestion as a
starting point to re-test, not a validated answer — drawdown scales
roughly with contract count since the entry/exit price logic doesn't
change, but stop-loss noise doesn't scale perfectly linearly in practice.
The daily kill switch (`dailyKillUSD`, currently a $900 placeholder in
both Pine scripts) only halts a single bad day — it does **not** by
itself protect against a trailing drawdown accumulated across multiple
days, so correct position sizing is still the primary defense, not the
kill switch.

One important reading note: a candidate can show a "held up" verdict
with a very small out-of-sample trade count (single digits) if the
in-sample search found an ultra-narrow combo that rarely fires. **Check
the `events` count on the out-of-sample line, not just the verdict** —
a handful of trades proves nothing regardless of the profit factor
attached to it.

This is a research tool, not a byte-for-byte replica of TradingView's
fill accounting — use it to narrow down promising parameter zones fast,
then confirm the final candidate in TradingView's Strategy Tester before
considering demo trading. Re-run it periodically (e.g., monthly) as new
data comes in rather than hand-tweaking parameters against whatever the
last TradingView screenshot happened to show — repeatedly tuning against
the same window is how you accidentally curve-fit without meaning to.

## How the strategy logic works (jarvis_meanrev_vwap_scaler.pine)

- **VWAP band**: price stretching beyond a volatility-based band around
  VWAP (2x ATR by default) is the setup — long when price is below the
  lower band, short when above the upper band (fading the extreme).
- **Range-bound filter**: only trades when ADX is **below** a threshold
  (default 20) — the inverse of the ORB script's filter, since mean-
  reversion works better when the market isn't trending strongly.
- **Volume**: requires a volume spike (1.5x the 20-bar average) at the
  extreme — treated as climax/exhaustion, not continuation confirmation.
- **Targets**: relative to the distance back to VWAP **at entry**, not
  open-ended ATR extensions — half the distance for the first partial,
  full VWAP touch for the rest, since the thesis is reversion to the
  mean, not a continuing trend.
- **Scale in**: adds to the position (up to a per-symbol cap) only once
  price is already moving back toward VWAP by a full ATR (confirmed
  reversion) with volume still elevated. Never adds while price keeps
  extending away from VWAP.
- **Stop loss**: ATR-based, beyond the entry price (reversion thesis
  invalidated if price keeps extending).
- **Daily kill switch**: flattens all positions and halts new entries once
  the day's cumulative loss hits a configured threshold — a safety buffer
  *below* Tradeify's actual daily loss limit, not the limit itself.
- **Session filter**: only enters new trades 9:30 AM–4:00 PM ET by default
  (stops/exits remain active at all times for safety).
- **On-chart status table**: shows daily P&L, kill switch state, current
  position, session status, ADX/range-bound state, VWAP band, and stop
  price directly on the TradingView chart.

## Project structure

```
pinescript/
  jarvis_meanrev_vwap_scaler.pine   # ACTIVE strategy - runs on TradingView
  jarvis_vwap_pullback_mnq.pine     # newest candidate, MNQ only - not yet validated
  jarvis_orb_vwap_scaler.pine       # ORB - reference only, no edge found
  jarvis_mnq_mes_scaler.pine        # EMA crossover - reference only, no edge found

backtest_optimizer.py  # walk-forward parameter search - run locally
strategy.py          # original Python/Lumibot version - reference only,
                      # cannot place live trades on a Sim Funded account
config.py             # constants for the Python version
shared_state.py        # file-based state store (Python version)
news_feed.py            # Alpha Vantage news fetcher
dashboard.py              # Flask dashboard (Python version)
templates/                  # dashboard HTML templates
test_connection.py            # Tradovate direct-API test - only relevant
                               # if you later upgrade to a Live Funded account
```

## Open items

- **VWAP band robustness check still pending on MNQ 5m** — a manual test
  found VWAP Band Multiple 2.5 outperforming the 2.0 default (PF 1.403 vs
  1.185) on the same June 22–today window. This has NOT yet been checked
  for robustness the way earlier fragile results were (e.g. testing 2.25
  and 2.75 to confirm it's a real neighborhood and not a lucky single
  value) or confirmed on a different, non-overlapping date range. Treat
  2.5 as promising but unconfirmed until both checks are done.
- **`vwap_pullback` MNQ 5-minute needs a sizing fix before it's tradeable**
  — real TradingView result was PF 1.527 / 52 trades / $4,928 net (real
  signal) but $3,570 max drawdown against the confirmed $2,000 account
  limit at 3/3/9 contract sizing. Run the updated `backtest_optimizer.py`
  (widened `stop_atr_mult` grid, drawdown-aware size suggestion in the
  report) locally, then confirm whichever config it suggests in
  TradingView before trusting it. 15-minute has no real edge (PF ~1.05)
  and is disabled by default via the Pine script's timeframe gate.
- **`meanrev`'s max drawdown has never been checked against the real
  $2,000 limit** — it was confirmed on profit factor alone (PF
  1.185–1.403) before the account's real drawdown limit was known. Run
  it through the updated optimizer (now tracks `max_drawdown` for every
  strategy) and check the same way `vwap_pullback` was checked, since
  it's the currently "active" script in the setup steps above.
- **`scalp` strategy (10-15 point fixed target, MNQ 1m/5m) is brand new
  and completely untested** — added to `backtest_optimizer.py` per a
  request for a quick-scalp approach distinct from the managed
  multi-bar positions the other strategies hold. No Pine Script exists
  for it yet and none should be built until it's been through the same
  walk-forward + TradingView confirmation process as everything else.
- **Real risk numbers, partially confirmed** — the account's max trailing
  drawdown is **confirmed at $2,000 (EOD trailing)**, separate from the
  known $1,250 daily loss limit on the $50K Lightning Funded account.
  `dailyKillUSD` (currently a $900 placeholder in the Pine Scripts) only
  guards a single day, not the cumulative trailing drawdown — see
  "Position sizing" above for how the $2,000 figure is actually being
  used (position sizing, not just the kill switch). Update `dailyKillUSD`
  / `RISK_PER_TRADE_USD` / `DAILY_KILL_SWITCH_USD` (`config.py`) to real
  values before trading real size, but don't treat the kill switch alone
  as sufficient protection.
- **Prop firm automation policy** — Tradeify's stated policy allows personal
  bots/scripts that are solely owned, not shared, and not HFT, plus a
  "microscalping rule" requiring over 50% of trades/profit to come from
  positions held longer than 10 seconds. Make sure the strategy's behavior
  stays within that as configured (the ATR-based holds should comfortably
  clear 10 seconds, but verify in practice).
- **PickMyTrade webhook wiring** — the exact JSON template must come from
  PickMyTrade's own generator (see setup steps above), not be hand-written.
- **Dashboard/news feed are currently disconnected from live trading** —
  they were built around the Python strategy pushing state to
  `runtime_state.json`, which no longer happens since the Pine Script
  strategy runs on TradingView, not in this Python process. Reconnecting
  them (e.g., via PickMyTrade's own trade history/API, if available) is a
  follow-up item, not yet done.
- **No historical backtest of the Pine Script version yet** — validate using
  TradingView's own Strategy Tester (built into Pine Editor) before going
  live.

## Risk disclaimer

This is a technical trading system built on sound but ordinary techniques
(momentum, volume confirmation, volatility-based risk sizing). It is not a
predictive system and does not "see the market coming" — no such system
exists. Past behavior of these signals is not a guarantee of future
performance. Test thoroughly (TradingView Strategy Tester, then
paper/demo routing) before risking a funded account, and never risk more
than you can afford to lose.
