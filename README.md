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

## Active setup: Pine Script + TradingView + PickMyTrade

1. Open TradingView, load an **MNQ1!** or **MES1!** continuous futures chart.
2. Open Pine Editor, paste in `pinescript/jarvis_mnq_mes_scaler.pine`, and
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

## How the strategy logic works

- **Entry signal**: EMA(9)/EMA(21) crossover, only acted on if current
  volume exceeds 1.5x its 20-bar average (momentum + volume confirmation,
  both long and short).
- **Scale in**: adds to a winning position (up to a per-symbol cap) only
  when price continues moving favorably by a full ATR with volume still
  confirming. Never adds to a loser.
- **Scale out**: takes partial profits in tranches as the trade extends
  (1x ATR, 2x ATR), trailing the stop on what's left.
- **Stop loss**: ATR-based, tightened as the position scales.
- **Daily kill switch**: flattens all positions and halts new entries once
  the day's cumulative loss hits a configured threshold — a safety buffer
  *below* Tradeify's actual daily loss limit, not the limit itself.
- **Session filter**: only enters new trades 9:30 AM–4:00 PM ET by default
  (stops/exits remain active at all times for safety).
- **On-chart status table**: shows daily P&L, kill switch state, current
  position, session status, and stop price directly on the TradingView
  chart.

## Project structure

```
pinescript/
  jarvis_mnq_mes_scaler.pine   # ACTIVE strategy - runs on TradingView

strategy.py         # original Python/Lumibot version - reference only,
                     # cannot place live trades on a Sim Funded account
config.py            # constants for the Python version
shared_state.py       # file-based state store (Python version)
news_feed.py           # Alpha Vantage news fetcher
dashboard.py             # Flask dashboard (Python version)
templates/                 # dashboard HTML templates
test_connection.py           # Tradovate direct-API test - only relevant
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
