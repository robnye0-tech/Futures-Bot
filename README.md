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

- **`jarvis_vwap_pullback_mnq.pine`** — **MNQ only, sizing not yet solved.**
  Trend-continuation (opposite mechanism from mean-reversion): trades
  WITH a moderately trending market (ADX in a band, not below a ceiling)
  on pullbacks to VWAP that get rejected and then break out in the trend
  direction. Auto-switches its ADX band / trend EMA lengths / stop
  multiple based on the chart's timeframe (input "Auto-Adjust Parameters
  By Chart Timeframe", default on) — drop it on a 1m/5m/15m MNQ chart
  without manually changing inputs. **Real TradingView results (June
  18–Aug 12 window):**
  - **5-minute**: PF 1.527, 52 trades, $4,928 net — a real signal, but
    **$3,570 max drawdown against the account's confirmed $2,000 EOD
    trailing drawdown limit** at the tested 3/3/9 contract sizing. **Not
    tradeable at that size as-is.** Tried tightening the stop
    (`stop_atr_mult` down to 0.5x ATR) in `backtest_optimizer.py` to see
    if smaller-risk-per-trade would allow more size — **it doesn't**: the
    0.5x-ATR configs came back OOS PF 0.000 (pure losses). The entries
    need room; the fix here is size reduction (roughly 1 base/3-4 max
    contracts at the original 1.5x ATR stop), not a tighter stop. Still
    needs a re-test at reduced size to confirm.
  - **15-minute**: real TradingView result was PF ~1.05 (essentially
    breakeven, no real edge) with the config found for that timeframe
    (ADX 20-40, EMA 10/100, stop 2.0x ATR). `backtest_optimizer.py`'s own
    search on this timeframe is unstable (candidates ranging from OOS PF
    1.3 with drawdown already over the $2,000 limit, to PF 7.4 on just 15
    trades — the small-sample-luck pattern flagged elsewhere in this
    README) and doesn't change that read. Entries are automatically
    disabled on 15-minute charts (and on any timeframe other than
    5-minute) via a validation gate — the on-chart status table's
    "Timeframe" row shows green when entries are live, orange when
    disabled.
  MES was dropped entirely per the same MNQ-only decision as
  mean-reversion. Commission ($1/contract) and slippage (2 ticks) are
  baked into the script.
- **`jarvis_scalp_vwap_cross_mnq.pine`** — **newest candidate, MNQ only,
  NOT YET VALIDATED against real TradingView data.** Different mechanism
  from the other three: fixed point target/stop, single entry,
  auto-close — no scale-in, no partials, no ATR. Entry on a fresh VWAP
  cross confirmed by fast EMA momentum + a volume spike.
  `backtest_optimizer.py` found target=12pts/stop=4-6pts/EMA 9/vol 1.2x
  on MNQ 5m: OOS PF 1.449, 48 trades, $796 net, $849 max drawdown at 2
  contracts — the first candidate this session that held up **without**
  needing a sizing rescue to fit the account's $2,000 drawdown limit.
  Still only tested on one ~10-week window (see "Getting a longer
  backtest window" below) — a hold-up on one window is promising, not
  proof.

## Active setup: signal-only, manual trading (current plan)

After the automated-execution path below was fully built out (PickMyTrade
webhook wiring, daily kill switch, position sizing), the decision was
made to **not** auto-execute trades — too much of this project's own
findings (drawdown blowing past account limits, outlier-dependent
"edges," sizing bugs) came from testing that logic, and a human staying
in the loop for every entry is a simpler, safer way to actually trade
this. The active plan now is a **signal-only indicator**, not a
strategy that places orders:

1. Open TradingView, load an **MNQ1!** continuous futures chart on a
   **5-minute timeframe** (the only timeframe with a real, confirmed
   `vwap_pullback` edge as of now).
2. Open Pine Editor, paste in
   `pinescript/jarvis_vwap_pullback_signals_mnq.pine`, and add it to the
   chart as an **indicator** (not a strategy — this one has no
   `strategy()` declaration, no simulated position, nothing to wire to a
   broker).
3. It plots LONG/SHORT triangle markers with a reference Stop/Target1/
   Target2 label at each signal — those levels are informational (same
   ATR multiples the backtested version uses), not orders. You decide
   position size, whether to take the signal, and how to manage the
   trade from there.
4. Right-click the chart → **Add Alert** → Condition → this indicator →
   pick "VWAP Pullback Long" or "VWAP Pullback Short" → set to "Once Per
   Bar Close" (not intrabar) → choose however you want to be notified
   (popup, sound, mobile push, email). No PickMyTrade, no webhook, no
   broker connection needed for this path.
5. **Before trusting any signal**, note the open caveats: the strategy
   version's real TradingView result was PF 1.527 / 52 trades / $4,928
   net with a $3,570 max drawdown against the account's $2,000 limit at
   3/3/9 sizing — reduced-size re-confirmation is still pending (see
   "Open items"). It also hasn't been checked for the same "Outliers
   PnL" concentration problem that showed up on the mean-reversion
   script (profit dominated by a handful of oversized trades, sub-50%
   win rate) — worth checking before trading these signals live.

### Alternative: full auto-execution (built, not currently in use)

The original plan wired a `strategy()` script's order-fill alerts to
[PickMyTrade](https://pickmytrade.trade/) to auto-execute on Tradeify.
That path still exists and works the same way for any of the `strategy()`
Pine Scripts in this repo (e.g. `jarvis_meanrev_vwap_scaler.pine`,
`jarvis_vwap_pullback_mnq.pine`) if the plan changes back to automation
later:

1. Load the strategy script on the chart, adjust inputs if needed
   (position sizing, ATR multiples, session hours, daily kill switch —
   **confirm the real Tradeify max trailing drawdown figure and set the
   kill switch comfortably below it**).
2. Sign up for PickMyTrade and connect your Tradeify/Tradovate account
   through their dashboard.
3. In PickMyTrade's dashboard, generate the webhook URL and JSON alert
   template for your account (**do not hand-write this JSON yourself** —
   use their generator, it embeds your account token correctly).
4. In TradingView, create an alert on the strategy (condition: "Order
   fills" or "Any alert() function call", whichever PickMyTrade's current
   docs specify), paste in the webhook URL and generated JSON template.
5. **Test in TradingView's Bar Replay / paper mode and against
   PickMyTrade's test/demo routing first.** Do not point a freshly-wired
   alert straight at a funded account.

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

It supports six strategy families (`crossover`, `orb`, `meanrev`,
`vwap_pullback`, `scalp`, `liquidity_sweep` — see `STRATEGIES` dict in
the script). `main()` currently runs, MNQ only (MES dropped):
- `vwap_pullback` on 5m/15m — the ADX 15-30/1.5x-ATR config keeps holding
  up out-of-sample across re-runs (latest: PF 1.087, 27 trades, $1,201.50
  max drawdown — now under the $1,300 safety budget at default 3/3/9
  sizing on this window) while every tighter-stop variant keeps failing.
  Real signal, needs a fresh TradingView confirmation pass at this
  config — see Pine Script section above and "Position sizing" below.

`scalp` and `liquidity_sweep` are no longer run by `main()` — both are
confirmed dead on real data (see their sections above). `meanrev`'s best
result (MNQ 5m) already has real TradingView confirmation — see the Pine
Script section above — but its most recent real test raised a serious
open question about whether that edge is repeatable (see "Open items").
`crossover` and `orb` are kept only for reference; both have already
been tested and shown to lack real out-of-sample edge.

### New: liquidity-sweep swing trade research (separate $2,000 cash account)

A different idea from everything above: swing-trade MNQ on a **separate
$2,000 cash account** (not the Tradeify prop account — same dollar
figure, unrelated accounts, don't confuse the two) using multi-timeframe
confluence — 4-hour structure for the setup, 1-hour for the entry
trigger — targeting liquidity sweeps (price briefly breaking a recent
high/low then rejecting back inside it) rather than multiple trades per
day. This is a recognized methodology (often called ICT / Smart Money
Concepts) with real backtested track records when the entry/exit rules
are fully objective — published rule-based backtests report 50-65% win
rates with profit factor above 1.5, well short of the 70-80% win rates
often claimed in ICT marketing content, which tend to come from
discretionary/cherry-picked examples rather than a codified system.

`run_backtest_liquidity_sweep()` in `backtest_optimizer.py` codifies it:
a "sweep" is a 4-hour bar (built by resampling 60-minute bars — Yahoo
has no native 4h interval) whose high/low exceeds a rolling N-bar extreme
and closes back inside it (the same rejection-then-breakout shape
`vwap_pullback` uses, applied to a rolling price extreme instead of
VWAP). Entry triggers on a 1-hour close beyond its own rolling extreme in
the reversal direction. No fixed take-profit — the stop trails to newly
formed 1-hour structure in the trade's favor instead, per the "let it
run" idea behind the original request.

**Position sizing was changed from the original proposal.** The
originally-described 20% stop-loss per trade ($400 on a $2,000 account)
would risk account ruin in roughly 5 losing trades — nowhere close to
safe even at a genuine 50-65% win rate. Position size (1-5 contracts, per
the original "1 to 5 micros" idea) is instead *derived* from the stop
distance to target a fixed `risk_pct` of the account per trade, defaulting
to **1% ($20/trade)** and grid-searched up to 2%. This keeps the "size
varies with setup" idea while keeping the risked fraction sane.

One practical bonus: this uses 60-minute data, which Yahoo allows up to
**~2 years back** — vastly more than the 60-day cap on 5m/15m data that's
limited every other result in this README to one test window. See
"Getting a longer backtest window" below for why that cap exists.

**Status: DEAD — real data, decisive negative result. Do not pursue this
exact design further.** Two sizing bugs were found and fixed along the
way (a minimum-1-contract floor that silently over-risked wide-stop
trades, and a reporting bug that showed the wrong account's drawdown
budget) — both are fixed and the diagnostics they left behind
(`signals_total` / `signals_skipped_undersized` / `avg_skipped_stop_distance`
on `run_backtest_liquidity_sweep()`'s stats, printed even when no
candidate survives) are still useful for any future strategy that sizes
off risk_pct. But once real trades were actually produced (`risk_pct`
widened to 5%, still nowhere near the original unsafe 20%), the result
was clear: **it loses money**, consistently, in both the in-sample and
out-of-sample windows, across multiple structural settings (`sweep_lookback_4h`
20 and 30 both showed net losses in-sample AND out-of-sample). The one
candidate that looked good (PF ~22) was built on 6 in-sample trades and
produced **zero trades in the entire ~9-month out-of-sample window** —
the same small-sample-luck pattern flagged elsewhere in this README
(the ORB 26-trade lead, vwap_pullback's 15-trade PF-7.39 spike), not a
real signal. This matches the risk flagged when this idea was first
discussed: ICT/Smart Money Concepts-style setups are notoriously hard to
reduce to fully objective, backtestable rules, and that's what happened
here when it was actually tried. Continuing to widen `risk_pct` or
reshuffle lookback windows chasing a positive number from here would be
curve-fitting, not research — the same mistake this whole project has
been built to avoid. Revisiting this idea would need a genuinely
different rule set, not more grid search on this one.

### Position sizing (Tradeify prop account): size from the drawdown budget, not from margin capacity

The Tradeify account allows up to 40 MNQ contracts on margin, but that
number is irrelevant to position sizing here — the account's real
constraint is a **$2,000 EOD trailing drawdown limit** (confirmed), which
is a much tighter ceiling. `_max_drawdown()` in `backtest_optimizer.py`
now tracks
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

### Running the research search on a schedule

`research_runner.py` wraps `backtest_optimizer.py` — same search, same
data, same output — but appends every run's results to a permanent,
timestamped log (`research_log.txt`, gitignored, stays local to your
machine) instead of only printing to the console. This is the practical
version of "let time accumulate and re-run periodically" from the
section below: run it weekly and you can compare whether the same
candidates keep showing up, rather than trusting any single pull.

```
python research_runner.py
```

**What this does NOT do**, worth being explicit about: it does not touch
TradingView, does not create or deploy any Pine Script, and does not
place or suggest a trade. It only re-runs the same local Python search
against fresh Yahoo Finance data and logs the result. Directly automating
TradingView itself (auto-generating/deploying Pine Scripts, reading
Strategy Tester results, "auto-learning" and redeploying) was considered
and deliberately not built — TradingView has no public API for any of
that, so the only way to do it would be browser automation clicking
through the website, which is fragile, likely against TradingView's
Terms of Service (real risk to the account actually used for trading),
and would remove the human confirmation step that's caught every
overfit/oversized candidate in this README so far. Every result from
`research_runner.py` still needs the same manual TradingView Strategy
Tester confirmation (profit factor, trade count, max drawdown vs. the
real $2,000 limit) as everything else here before it's trusted.

To run it automatically on a schedule (Windows Task Scheduler, from
PowerShell — adjust the paths to match your setup):

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\gamel\Futures-Bot\venv\Scripts\python.exe" `
    -Argument "research_runner.py" `
    -WorkingDirectory "C:\Users\gamel\Futures-Bot"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 6am
Register-ScheduledTask -TaskName "FuturesBotWeeklyResearch" -Action $action -Trigger $trigger
```

That registers a task that runs `research_runner.py` every Monday at
6 AM using the project's venv, appending to `research_log.txt` each
time. Check `research_log.txt` periodically (or open it directly) to see
the accumulated history. To remove it later:
`Unregister-ScheduledTask -TaskName "FuturesBotWeeklyResearch"`.

### Getting a longer backtest window

Every `backtest_optimizer.py` result so far is limited to one window:
Yahoo Finance's own caps are the hard ceiling (`INTERVAL_MAX_RANGE` in
the script) — **60 days** for 5-minute/15-minute bars, 7 days for
1-minute. That's not a bug to fix, it's the free data source's real
limit, and it's why every result in this README says "one window" and
gets treated as promising-not-proof rather than confirmed. Realistic
options, roughly cheapest to most involved:

1. **Let time accumulate and re-run periodically.** Each week that
   passes is another week of real fresh out-of-sample data. Re-running
   `backtest_optimizer.py` every week or two and keeping a log of the
   results (which candidates keep holding up vs. which stop doing so)
   builds an accumulating track record without needing a bigger single
   pull. This is the free, no-effort option and honestly the most
   reliable one — a strategy that keeps holding up across several
   separately-drawn windows over time is stronger evidence than one big
   backtest ever is.
2. **Check what TradingView's own chart already shows before assuming
   you need Premium.** Depending on your plan tier, TradingView may
   already display more than 60 days of 5-minute MNQ history on the
   chart itself — if so, you can run the Strategy Tester against that
   longer range directly, no Deep Backtesting purchase needed. Worth
   checking before spending anything.
3. **TradingView Premium's Deep Backtesting** (~$70/mo) — the paid
   option for full intraday history beyond what your current plan shows.
   This was already considered once this session and declined given how
   thin the lead being investigated was at the time; worth reconsidering
   now that `vwap_pullback` and `scalp` are more developed, but it's a
   real recurring cost, not a one-time unlock.
4. **A longer window is already available for free, just at a coarser
   granularity**: Yahoo's `60m` (hourly) bars go back up to ~2 years,
   vastly more than the 60-day cap on 5m/15m. None of the current
   strategies are tuned for hourly bars, so this isn't a drop-in test of
   what's already been built — but if a strategy idea could reasonably
   work on an hourly timeframe, this is a free lever nobody has pulled
   yet.
5. **A paid intraday data vendor** (e.g. Databento, Polygon, Norgate) —
   the most capable option (real tick/minute history for years back) but
   a real integration effort and ongoing cost, not a quick change to
   `backtest_optimizer.py`. Only worth it if this becomes a long-term,
   heavily-relied-on tool rather than the current research/validation
   role it plays.

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
  jarvis_vwap_pullback_signals_mnq.pine  # ACTIVE - signal-only indicator, manual trading
  jarvis_vwap_pullback_mnq.pine     # same logic as a strategy() - auto-exec alternative, sizing not yet solved
  jarvis_meanrev_vwap_scaler.pine   # real edge but outlier-dependent (see Open items) - not currently used
  jarvis_scalp_vwap_cross_mnq.pine  # confirmed dead - reference only
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
  limit at 3/3/9 contract sizing. Tightening the stop to fix this was
  tried and **failed** (0.5x ATR broke the edge, OOS PF 0.000) — the fix
  is reduced size (roughly 1 base/3-4 max contracts) at the original 1.5x
  ATR stop, not yet re-confirmed in TradingView at that size. 15-minute
  has no real edge (PF ~1.05) and is disabled by default via the Pine
  script's timeframe gate.
- **`meanrev` is answered, and not favorably: its "edge" is outlier-
  dependent, not real in the repeatable sense.** Real TradingView test
  (Jun 28–Aug 20 window): Total PnL $15,538.50, but **Outliers PnL was
  $17,893.50 — more than the entire net profit.** Strip the outlier
  trades out and this strategy nets to roughly **-$2,355**. Win rate was
  48.15% (26/54), below 50%. Max drawdown $6,801.50, over 3x the
  confirmed $2,000 account limit. This is the same
  data/window-overlap issue as before (max drawdown, largest win/loss
  all identical to the prior test — not independent confirmation, same
  underlying Aug 3–7 trade cluster), but the Outliers PnL metric itself
  is decisive on its own: this is not a strategy with a real edge on
  typical trades, it's a sub-50%-win-rate strategy rescued by a handful
  of oversized trades. Not currently in use — `vwap_pullback` (as a
  signal-only indicator, see "Active setup") is the current plan
  instead. **`vwap_pullback` itself has never been checked for this
  same outlier-dependency problem** — do that before trusting it either.
- **`scalp` is confirmed dead at both target scales.** Original 8-15pt
  target: real TradingView result PF 1.067, win rate 34.69% (barely
  above the mathematical breakeven of 33.3% for its own 2:1
  target:stop). Widened 20-40pt "quick move" target (same fresh-VWAP-
  cross-+-EMA-momentum-+-volume entry trigger, tried per a request to
  test a real momentum-scale move instead of a noise-scale one): all
  three top candidates showed out-of-sample PF below 1.0 (0.793, 0.865,
  0.811) on real sample sizes (50-52 OOS trades each) — decisive enough
  in the Python search alone that a TradingView round-trip wasn't needed
  to confirm it. The entry trigger itself doesn't have real edge at any
  target scale tried. `jarvis_scalp_vwap_cross_mnq.pine` stays in the
  repo for reference; no Pine Script was built for the wider-target
  version since it never cleared the Python walk-forward bar. Not
  re-run by `main()` anymore.
- **`liquidity_sweep` is confirmed dead** — see "New: liquidity-sweep
  swing trade research" above. Two real sizing bugs were found and fixed
  along the way, but once real trades were produced at a safe risk_pct
  (up to 5%), the result was a consistent net loss in-sample and
  out-of-sample across multiple settings. Not a candidate as designed;
  would need a genuinely different rule set to revisit, not more tuning.
- **Every result in this repo is from a single ~10-week backtest window**
  — see "Getting a longer backtest window" above for real options (none
  of them free AND unlimited). Treat every "held up out-of-sample"
  verdict as promising, not proof, until it's been checked against a
  second, separately-drawn window.
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
