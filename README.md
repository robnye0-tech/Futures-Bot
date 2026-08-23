# Futures Bot

VWAP Pullback Trend-Continuation strategy for MNQ (Micro Nasdaq) futures,
built for a Tradeify Sim Funded account. One strategy, dialed in
properly, instead of spreading effort across candidates.

## Architecture note (read this first)

The original plan was a pure Python bot (Lumibot) connecting directly to
Tradovate's API. **That path does not work for Sim Funded prop firm
accounts** — Tradovate only issues API credentials (CID/Secret) for Live
Funded accounts. Sim Funded accounts must automate through the trading
platform itself instead — Pine Script running on TradingView, with
`strategy.py` and its supporting files (`config.py`, `dashboard.py`,
`shared_state.py`, `news_feed.py`, `templates/`) kept only as reference
from that earlier direct-API attempt; they cannot place live trades on
this account.

## The strategy: VWAP Pullback Trend-Continuation (MNQ, 5-minute)

Trades **with** a moderately trending market (ADX in a band — not
range-bound, not extreme) on pullbacks to VWAP that hold: a "rejection
candle" dips to/through VWAP and closes back on the trend side, and a
later bar breaking that candle's high/low triggers the entry in the
trend direction. Real TradingView confirmation on the 5-minute default
(ADX 15–30, trend EMA 10/50, 1.5x ATR stop): **PF 1.527, 52 trades,
$4,928 net** — a real signal. Since then it's kept reconfirming across
multiple rolling-data re-runs, most recently **PF 1.763 on 29
out-of-sample trades**, drawdown comfortably under budget.

**Sizing: RESOLVED, confirmed in real TradingView data.** At the
originally-tested 3-base/9-max sizing, real drawdown hit $3,570 against
the account's confirmed **$2,000 EOD trailing drawdown limit** — not
tradeable. Tightening the stop was tried and **failed** (0.5x ATR broke
the edge). A reduced-size Python suggestion (base=1/max=3) was tried in
real TradingView next and also **failed** (PF 0.509, net -$2,652.50) —
but its signal breakdown isolated the real cause: **the base pullback
entries were profitable on their own** (+$1,026 net) while the
**scale-in adds lost money** (-$3,678.50), because scaling in reset the
stop to a tighter level from the current price at the same moment the
position got bigger, letting a normal pullback stop out the whole
enlarged position.

**Fix: disable scale-in entirely — addSize=0, maxSize=baseSize.**
Confirmed clean in real TradingView at base=1: **PF 1.825, 19 trades,
68.42% win rate, $934.50 net, $443.50 max drawdown.** Outliers PnL was
**negative** (-$339.50) — the opposite of an outlier-propped-up result,
the exact check that killed a different candidate earlier in this
project.

**Current default: base=2, addSize=0, maxSize=2**, also confirmed clean
over the same date range: **PF 2.272, 32 trades, 81.25% win rate,
$2,880.50 net, $887.00 max drawdown**, Outliers PnL again negative
(-$679.00). This is *not* just base=1 doubled — the partial-exit calls
use `qty_percent = 33`, which rounds to 0 contracts at base=1 (so
Target 1/2 scale-outs never actually fire at that size, every trade
rides the raw or breakeven stop) but rounds to a real 1-contract close
at base=2+ (partial profit-taking actually engages). That's the real
explanation for why trade count and win rate both moved between the two
sizes — a genuinely different exit mechanism, not a linear scale-up.
Both Pine Scripts default to base=2/addSize=0/maxSize=2 now. Sample size
(32 trades) is still modest, which is exactly what the paper trading
week below is for.

15-minute has no real edge (PF ~1.05 on real TradingView data) and is
disabled by default in the Pine scripts via a timeframe-validation gate
— kept only as a standing comparison in the backtest, not a live option.

## Active setup: paper trading test (current step)

**Current plan**: run `pinescript/jarvis_vwap_pullback_mnq.pine` (the
`strategy()` version) connected to **TradingView's own built-in Paper
Trading broker** — not PickMyTrade, not real money — for a full week,
to get a genuine live-data track record before ever considering a
funded account.

1. Open TradingView, load **MNQ1!** continuous futures on a
   **5-minute** chart (the only timeframe with confirmed edge).
2. Paste `jarvis_vwap_pullback_mnq.pine` into Pine Editor, add it to the
   chart as a strategy. Inputs already default to the confirmed sizing
   (base=2, addSize=0, maxSize=2 — see "The strategy" above) and the
   correct 5-minute config via "Auto-Adjust Parameters By Chart
   Timeframe" (on by default) — no inputs need touching.
3. Open the Trading Panel at the bottom of the chart and connect the
   strategy to TradingView's Paper Trading account (no PickMyTrade
   needed for this step — that's only for real execution later).
4. Let it run untouched for a full week.
5. At the end, check the same screens every other candidate got checked
   with: Key Stats (PF, max drawdown), Trades Analysis / Outliers PnL
   (win rate, whether profit is outlier-dependent). Only after a clean
   week does a funded account become a reasonable next conversation.

**Alternative, if a human-in-the-loop approach is preferred instead or
alongside**: `pinescript/jarvis_vwap_pullback_signals_mnq.pine` is an
`indicator()` version of the same logic — plots LONG/SHORT markers with
reference Stop/Target1/Target2 levels and fires TradingView alerts
without placing any orders. Set any alert on it to **"Once Per Bar
Close"** (not intrabar) — that's what stops the bot (or you) from
acting on a signal that showed up mid-candle and reversed before the
bar closed.

### Moving to a funded account later

Once a paper trading week (or several) comes back clean, the path to
real execution is `jarvis_vwap_pullback_mnq.pine` plus
[PickMyTrade](https://pickmytrade.trade/): confirm the daily kill switch
figure, connect PickMyTrade to Tradeify/Tradovate, generate the webhook
URL and JSON alert template from PickMyTrade's own dashboard (never
hand-write that JSON), and wire a TradingView alert on the strategy to
it. Test against PickMyTrade's demo routing before pointing anything at
a funded account. The strategy keeps `calc_on_every_tick = false` and
`process_orders_on_close = true` in its declaration regardless of
deployment target — trades only on a fully closed candle's confirmed
signal, never an intrabar tick that could still reverse.

## Parameter tuning: use the optimizer, don't hand-tweak in TradingView

`backtest_optimizer.py` runs a proper walk-forward parameter search
locally (needs normal internet access):

```
python backtest_optimizer.py
```

What it does:
1. Pulls free historical MNQ data (5-min/15-min bars: ~60 days — Yahoo's
   own limit, not something we can change without a paid data source).
2. Splits it chronologically: first 70% = in-sample (used for search),
   last 30% = out-of-sample (never touched during search).
3. Grid-searches ADX band / trend EMA lengths / stop multiple on
   in-sample data only, and scores candidates by how consistently they
   perform across nearby settings (robust), not just whichever single
   combo peaked highest (likely overfit).
4. Takes the most robust candidate and runs it ONCE, unchanged, on the
   out-of-sample data. **That out-of-sample number is the one to
   trust** — if profit factor holds above 1.0 there, it's a real signal;
   if it collapses, the in-sample result was noise.
5. Flags any candidate whose out-of-sample max drawdown exceeds the
   $1,300 safety budget (under the real $2,000 account limit) with a
   rough linear-scaling size suggestion — treat that as a starting point
   to re-test, not a validated answer.
6. Runs a **sizing sweep**: the confirmed-good config (ADX 15-30, trend
   EMA 10/50, 1.5x ATR stop) at seven explicit contract sizes on the
   full dataset, printing PF/events/net/drawdown side by side so it's
   clear which sizes actually fit the account's real limit — directly,
   not via linear-scaling guesses.

One important reading note: a candidate can show a "held up" verdict
with a very small out-of-sample trade count (single digits) if the
in-sample search found an ultra-narrow combo that rarely fires. **Check
the `events` count on the out-of-sample line, not just the verdict** —
a handful of trades proves nothing regardless of the profit factor
attached to it.

This is a research tool, not a byte-for-byte replica of TradingView's
fill accounting — use it to narrow down promising parameter zones fast,
then confirm the final candidate in TradingView's Strategy Tester before
considering demo trading.

### Running the research search on a schedule

`research_runner.py` wraps `backtest_optimizer.py` — same search, same
data, same output — but appends every run's results to a permanent,
timestamped log (`research_log.txt`, gitignored, stays local to your
machine) instead of only printing to the console:

```
python research_runner.py
```

It does not touch TradingView, does not create or deploy any Pine
Script, and does not place or suggest a trade — it only re-runs the
local Python search against fresh Yahoo data and logs the result. Every
result still needs the same manual TradingView Strategy Tester
confirmation as everything else here.

To run it automatically on a schedule (Windows Task Scheduler, from
PowerShell — adjust the paths to match your setup):

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\gamel\Futures-Bot\venv\Scripts\python.exe" `
    -Argument "research_runner.py" `
    -WorkingDirectory "C:\Users\gamel\Futures-Bot"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 6am
Register-ScheduledTask -TaskName "FuturesBotWeeklyResearch" -Action $action -Trigger $trigger
```

Check `research_log.txt` periodically to see the accumulated history. To
remove it later: `Unregister-ScheduledTask -TaskName "FuturesBotWeeklyResearch"`.

### Getting a longer backtest window

Every result so far is limited to one ~60-day window — Yahoo Finance's
own cap on 5-minute/15-minute data (`INTERVAL_MAX_RANGE` in the script).
That's the free data source's real limit, not a bug to fix. Options,
roughly cheapest to most involved:

1. **Let time accumulate and re-run periodically.** Each week is another
   week of real fresh out-of-sample data — a strategy that keeps holding
   up across several separately-drawn windows over time is stronger
   evidence than one big backtest ever is. This is what
   `research_runner.py` is for.
2. **Check what TradingView's own chart already shows** before assuming
   you need Premium — depending on plan tier it may already display more
   than 60 days of 5-minute history.
3. **TradingView Premium's Deep Backtesting** (~$70/mo) — the paid
   option for full intraday history beyond your current plan.
4. **Yahoo's `60m` (hourly) bars go back ~2 years** — free, but the
   current strategy isn't tuned for that granularity.
5. **A paid intraday data vendor** (Databento, Polygon, Norgate) — real
   tick/minute history for years back, real integration effort and
   ongoing cost.

## Position sizing: size from the drawdown budget, not from margin capacity

The Tradeify account allows up to 40 MNQ contracts on margin, but that
number is irrelevant to position sizing here — the account's real
constraint is the **$2,000 EOD trailing drawdown limit**, a much
tighter ceiling. `backtest_optimizer.py` tracks peak-to-trough drawdown
on the closed-trade equity curve and flags any candidate whose
out-of-sample max drawdown exceeds `DRAWDOWN_SAFETY_BUDGET` ($1,300 — a
buffer below the real $2,000 limit) with a rough linear-scaling size
suggestion. Drawdown scales roughly with contract count since the
entry/exit price logic doesn't change, but stop-loss noise doesn't
scale perfectly linearly in practice — always re-test at the suggested
size rather than trusting the scaling math alone.

The daily kill switch (`dailyKillUSD`, currently a $900 placeholder in
the Pine Script) only halts a single bad day — it does **not** by
itself protect against a trailing drawdown accumulated across multiple
days. Correct position sizing is the primary defense, not the kill
switch.

## Project structure

```
pinescript/
  jarvis_vwap_pullback_signals_mnq.pine  # ACTIVE - signal-only indicator, manual trading
  jarvis_vwap_pullback_mnq.pine          # same logic as a strategy() - auto-exec alternative

backtest_optimizer.py  # walk-forward parameter search - run locally
research_runner.py     # scheduled wrapper that logs backtest_optimizer.py's output

strategy.py, config.py, shared_state.py, news_feed.py, dashboard.py,
templates/, test_connection.py, requirements.txt
  # original Python/Lumibot direct-API version - reference only,
  # cannot place live trades on a Sim Funded account
```

## Open items

- **Sizing and outlier-dependency both resolved and confirmed in real
  TradingView data** — current default base=2/addSize=0/max=2 (scale-in
  disabled, both sizes equal): PF 2.272, 32 trades, 81.25% win rate,
  $2,880.50 net, $887.00 max drawdown, Outliers PnL **negative**
  (-$679.00 — the opposite of the outlier-propped-up problem that killed
  an earlier candidate). base=1/addSize=0/max=1 also confirmed clean
  separately (PF 1.825, 19 trades, $443.50 max drawdown) — the two sizes
  aren't linear scalings of each other, since `qty_percent = 33` partial
  exits only actually fire at base=2+ (see "The strategy" above). Both
  Pine Scripts default to base=2/addSize=0/max=2. Open step now is the
  paper trading week (see "Active setup" above) to build real confidence
  beyond this one 32-trade confirmation, not another sizing question.
- **Every result is from a single ~60-day backtest window** — see
  "Getting a longer backtest window" above. Treat "held up
  out-of-sample" as promising, not proof, until confirmed on a second,
  separately-drawn window.
- **Real risk numbers, partially confirmed** — the account's max
  trailing drawdown is confirmed at $2,000 (EOD trailing), separate from
  the known $1,250 daily loss limit on the $50K Lightning Funded
  account. `dailyKillUSD` is currently a $900 placeholder — update it
  and `RISK_PER_TRADE_USD` / `DAILY_KILL_SWITCH_USD` (`config.py`) to
  real values before trading real size.
- **Prop firm automation policy** — Tradeify's stated policy allows
  personal bots/scripts that are solely owned, not shared, and not HFT,
  plus a "microscalping rule" requiring over 50% of trades/profit to
  come from positions held longer than 10 seconds. The ATR-based holds
  should comfortably clear that, but verify in practice if automation
  is ever turned back on.
- **Dashboard/news feed are disconnected from live trading** — built
  around the old Python strategy pushing state to `runtime_state.json`,
  which doesn't happen now that the strategy runs on TradingView.
  Reconnecting them (e.g. via PickMyTrade's trade history/API, if
  available) is a follow-up item, not started.

## Risk disclaimer

This is a technical trading system built on sound but ordinary techniques
(momentum, volume confirmation, volatility-based risk sizing). It is not a
predictive system and does not "see the market coming" — no such system
exists. Past behavior of these signals is not a guarantee of future
performance. Test thoroughly (TradingView Strategy Tester, then
paper/demo routing) before risking a funded account, and never risk more
than you can afford to lose.
