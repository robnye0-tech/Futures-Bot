# Futures Bot

Momentum/volume scale-in-out trading strategy for MNQ (Micro Nasdaq) and MES
(Micro S&P 500) futures, built for a Tradeify funded account via Tradovate.
Includes a local status dashboard with an account overview, live positions,
trade log, and a Nasdaq/tech-relevant news feed.

## Status

**Not yet live.** The trading logic is complete, but it is not connected to
a broker yet. See [Open items](#open-items) below.

## How it works

- **Entry signal**: EMA(9)/EMA(21) crossover on 1-minute bars, only acted on
  if current volume exceeds 1.5x its 20-bar average (momentum + volume
  confirmation, both long and short).
- **Scale in**: adds to a winning position (up to a per-symbol cap) only when
  price continues moving favorably by a full ATR with volume still
  confirming. Never adds to a loser.
- **Scale out**: takes partial profits in tranches as the trade extends
  (1x ATR, 2x ATR), trailing the stop on what's left.
- **Stop loss**: ATR-based, tightened as the position scales.
- **Daily kill switch**: flattens all positions and halts new entries once
  the day's cumulative loss hits a configured threshold — a safety buffer
  *below* Tradeify's actual daily loss limit, not the limit itself.
- **Session filter**: only trades 9:30 AM–4:00 PM ET by default.
- **News feed**: pulls Nasdaq/tech/macro-relevant headlines (Alpha Vantage
  News & Sentiment) into the dashboard on a timer.

All tunable parameters live in `config.py`.

## Project structure

```
strategy.py       # the trading logic (Lumibot Strategy)
config.py         # all tunable constants in one place
shared_state.py    # file-based state store shared between strategy and dashboard
news_feed.py       # Alpha Vantage news fetcher
dashboard.py        # Flask dashboard (Overview / Positions / Trade Log / News)
templates/           # dashboard HTML templates
```

The strategy process and the dashboard process are independent — the
strategy writes its state to `runtime_state.json`, and the dashboard just
reads and displays it. Run them in two separate terminals.

## Setup

1. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\Activate.ps1      # Windows
   # source venv/bin/activate     # Mac/Linux
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your real credentials:
   ```
   copy .env.example .env          # Windows
   # cp .env.example .env          # Mac/Linux
   ```

3. Run the strategy:
   ```
   python strategy.py
   ```

4. In a separate terminal (same venv activated), run the dashboard:
   ```
   python dashboard.py
   ```
   Then open http://127.0.0.1:5000 in a browser.

## Open items

- **Tradovate API credentials** — request these through Tradovate's API
  access program / your Tradeify account before the strategy can connect to
  anything. Until `.env` has real `TRADOVATE_*` values, `strategy.py` will
  not run.
- **Confirm real risk numbers** — `RISK_PER_TRADE_USD` and
  `DAILY_KILL_SWITCH_USD` in `config.py` are conservative placeholders.
  Confirm Tradeify's actual max trailing drawdown figure (separate from the
  known $1,250 daily loss limit on the $50K Lightning Funded account) and
  update these before trading real size.
- **Prop firm automation policy** — verify directly with Tradeify/Tradovate
  that automated/algorithmic trading is permitted on your specific account
  tier before going live. Policies vary and change over time.
- **No historical backtest yet** — futures historical data isn't free the
  way stock data is; this strategy is designed to be validated live against
  Tradovate's demo/paper account first rather than an offline backtest.
  Do not skip demo testing before risking a funded account.
- **Alpha Vantage free tier is rate-limited** — the news feed refreshes on a
  timer (`NEWS_REFRESH_MINUTES` in `config.py`), not every iteration, to
  stay within free-tier limits.

## Risk disclaimer

This is a technical trading system built on sound but ordinary techniques
(momentum, volume confirmation, volatility-based risk sizing). It is not a
predictive system and does not "see the market coming" — no such system
exists. Past behavior of these signals is not a guarantee of future
performance. Test thoroughly on a demo/paper account before risking a
funded account, and never risk more than you can afford to lose.
