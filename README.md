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

- **`jarvis_orb_vwap_scaler.pine`** — **current candidate.** Opening Range
  Breakout + VWAP confluence + volume + ADX momentum filter. Plots the OR
  high/low directly on the chart as a visual reference.
- `jarvis_mnq_mes_scaler.pine` — EMA crossover version. Walk-forward tested
  (see `backtest_optimizer.py` and the "Open items" section) and found to
  have **no real out-of-sample edge** on MNQ/MES. Kept for reference only —
  do not use this one going forward.

## Active setup: Pine Script + TradingView + PickMyTrade

1. Open TradingView, load an **MNQ1!** or **MES1!** continuous futures chart.
2. Open Pine Editor, paste in `pinescript/jarvis_orb_vwap_scaler.pine`, and
   add it to the chart as a strategy.
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

It supports two strategy families (`crossover` and `orb`, see
`STRATEGIES` dict in the script) — `orb` (Opening Range Breakout + VWAP +
ADX) is the current candidate and what `main()` runs by default. The
crossover version is kept only for reference/comparison; it's already
been tested and shown to lack real edge.

This is a research tool, not a byte-for-byte replica of TradingView's
fill accounting — use it to narrow down promising parameter zones fast,
then confirm the final candidate in TradingView's Strategy Tester before
considering demo trading. Re-run it periodically (e.g., monthly) as new
data comes in rather than hand-tweaking parameters against whatever the
last TradingView screenshot happened to show — repeatedly tuning against
the same window is how you accidentally curve-fit without meaning to.

## How the strategy logic works (jarvis_orb_vwap_scaler.pine)

- **Opening Range**: tracks the high/low of the first N minutes of the
  session (15 min by default), plotted on the chart as step-lines so you
  can see it directly, plus a shaded background during the OR formation
  window.
- **Entry signal**: a close breaking above the OR high (long) or below
  the OR low (short), confirmed by VWAP confluence (price must also be on
  the correct side of VWAP), volume exceeding 1.5x its 20-bar average,
  and ADX above a threshold (momentum/trend-strength — filters out weak,
  choppy breakouts).
- **Scale in**: adds to a winning position (up to a per-symbol cap) only
  when price continues moving favorably by a full ATR with volume still
  confirming. Never adds to a loser.
- **Scale out**: takes partial profits in tranches as the trade extends
  (1x ATR, 2x ATR), trailing the stop on what's left.
- **Stop loss**: ATR-based, tightened as the position scales.
- **Daily kill switch**: flattens all positions and halts new entries once
  the day's cumulative loss hits a configured threshold — a safety buffer
  *below* Tradeify's actual daily loss limit, not the limit itself.
- **Session filter**: only enters new trades 9:30 AM–4:00 PM ET by default,
  and only after the opening range window has closed (stops/exits remain
  active at all times for safety).
- **On-chart status table**: shows daily P&L, kill switch state, current
  position, session status, OR high/low, ADX, and stop price directly on
  the TradingView chart.

## Project structure

```
pinescript/
  jarvis_orb_vwap_scaler.pine   # ACTIVE strategy - runs on TradingView
  jarvis_mnq_mes_scaler.pine    # EMA crossover - reference only, no edge found

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

- **Confirm real risk numbers** — `dailyKillUSD` in the Pine Script (and
  `RISK_PER_TRADE_USD` / `DAILY_KILL_SWITCH_USD` in `config.py`) are
  conservative placeholders. Confirm Tradeify's actual max trailing
  drawdown figure (separate from the known $1,250 daily loss limit on the
  $50K Lightning Funded account) and update these before trading real size.
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
