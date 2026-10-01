# CLAUDE.md

Repo-level rules. The `auto-optimize` branch section is the durable
version of the rules `orchestrator.py` was built under - read it before
touching anything on that branch, whether by hand or by running the
script.

## What this repo is

`jarvis_vwap_pullback_mnq.pine` is a real Pine Script strategy that, when
live, drives REAL broker execution on a Tradeify/Tradovate account via
TradingView alerts -> PickMyTrade -> Tradovate (see `GOING_LIVE.md`).
`backtest_optimizer.py` is a separate, pure-Python research tool that
re-implements the same strategy logic to test parameters quickly against
Yahoo Finance data, independent of TradingView. `strategy.py`,
`config.py`, `dashboard.py`, `shared_state.py`, `news_feed.py`, and
`test_connection.py` are an earlier, separate Python/lumibot live-trading
stack that is NOT currently used for live trading - real live trading
goes through the Pine Script path above, not this one.

## `auto-optimize` branch rules

This branch hosts an automated parameter-search loop (`orchestrator.py`)
over `backtest_optimizer.py`'s `vwap_pullback` backtest. The loop is
allowed to run unattended, make its own commits, and iterate - but only
within these boundaries:

1. **Branch-scoped.** All work happens on `auto-optimize`. Never merge
   into or commit directly to `main` from this workflow.
2. **Data is split and the holdout is sacred.** MNQ 5m bars are fetched
   from Yahoo once per optimization run and cached to
   `data/mnq_5m_cache.json`, split chronologically ~75% in-sample / ~25%
   holdout. Every search decision uses the in-sample data only. The
   holdout set is evaluated exactly once, at the very end, on the single
   best in-sample candidate - never used to pick or compare parameters
   during the search itself.
3. **One change per iteration, always committed.** Each iteration of
   `orchestrator.py` changes exactly one key in `strategy_params.py` (a
   mini grid search over that key's own candidate values, scored on
   in-sample data) and commits - whether or not anything actually
   changed, with a message explaining what was tried and why.
4. **Every run's metrics are logged.** Every candidate evaluated, not
   just the one kept, is appended to `results/log.csv`: net profit,
   profit factor, max drawdown, win rate, trade count, and confirmation
   that commissions/slippage are included (they're baked into net P&L by
   the engine's existing fill accounting).
5. **Never edit the backtest engine, the data files, or any
   live-trading code.**
   - `backtest_optimizer.py` is the engine. The one approved exception
     (already made, see its git history) was a 4-line additive-only
     instrumentation change exposing win rate / trade count - no
     existing calculation changed. No further edits to this file from
     this workflow.
   - `data/mnq_5m_cache.json` is fetched once and then read-only for the
     rest of that run - the loop never edits or re-fetches it mid-run.
   - `strategy.py`, `config.py`, `dashboard.py`, `shared_state.py`,
     `news_feed.py`, `test_connection.py`, and everything under
     `pinescript/` must never be touched by this workflow, ever.
   - Only `strategy_params.py` is mutated by the loop, and only its
     `PARAMS` dict - never `FIXED`.
6. **Fixed, non-optimizable values.** Position sizing (`base_size`,
   `add_size`, `max_size`) and the safety rails (`force_flat_time`,
   `daily_kill_usd`, `cumulative_kill_usd`, `cumulative_kill_persists`)
   live in `strategy_params.py`'s `FIXED` dict and are never touched by
   the search - sizing is an account-fit question separate from signal
   quality, and an automated loop must never be able to loosen a safety
   rail just to make a run's numbers look better.
7. **No live account connection, ever.** This workflow's only network
   call is the one-time Yahoo historical-data fetch. It never imports
   anything from the live-trading stack and never talks to
   Tradovate/PickMyTrade/Tradeify in any way.
8. **Commits, not pushes, by default.** `orchestrator.py` commits
   locally every iteration. It does not push unless run with `--push`.
   Review the commits yourself before sharing the branch.

See `orchestrator.py`'s own docstring for exactly how to run it
(`python orchestrator.py`, needs real internet access to reach Yahoo on
the first run - same limitation `backtest_optimizer.py` already
documents, which is why this has to run on your own machine, not inside
a sandboxed session).
