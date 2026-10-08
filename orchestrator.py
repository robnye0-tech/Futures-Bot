"""
Automated, Windows-runnable parameter optimization loop for the
vwap_pullback strategy's Python backtest (backtest_optimizer.py).

WHY THIS EXISTS: a disciplined, auditable alternative to manually tweaking
one parameter at a time - every change is logged, committed, and explained,
and the final candidate is only ever judged on data it never saw.

RULES THIS SCRIPT ENFORCES (durable copy in CLAUDE.md):
  - Only ever runs on, and commits to, the `auto-optimize` branch. Refuses
    to run anywhere else, especially `main`.
  - Fetches MNQ 5m bars from Yahoo ONCE per data/mnq_5m_cache.json, and
    reuses that exact cache for every iteration of a given optimization
    run - never re-fetches mid-run. A fresh fetch mid-run would shift
    Yahoo's rolling 60-day window and make iterations incomparable.
  - Splits that cache chronologically: the oldest ~75% is in-sample (used
    for every search decision below); the newest ~25% is the holdout -
    loaded once but never evaluated until the single final run.
  - Each iteration changes exactly ONE key in strategy_params.py (a mini
    grid search over that key's candidates only, scored on in-sample data)
    and commits - win or "no improvement found" alike, so every iteration
    produces one explained commit.
  - Never imports, calls, or edits anything related to live trading
    (strategy.py, config.py, dashboard.py, shared_state.py, news_feed.py,
    test_connection.py, pinescript/) and never opens a network connection
    to a broker - the only network call this script makes is the one-time
    Yahoo historical-data fetch, and only if the cache doesn't exist yet.
  - Never edits backtest_optimizer.py (the backtest engine) or main.

Run on Windows (needs real internet access to reach Yahoo on first run -
this cannot run inside a sandboxed/offline dev session, same limitation
backtest_optimizer.py's own docstring documents):

    python orchestrator.py                  # default: 10 iterations
    python orchestrator.py --iterations 20
    python orchestrator.py --push           # push the branch after finishing

By default this script COMMITS locally every iteration but does NOT push -
review `git log` / `git diff` on the auto-optimize branch yourself, then
push when you're satisfied (or pass --push to have it push once at the
very end, after the holdout confirmation).
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime

from backtest_optimizer import fetch_bars, run_backtest_vwap_pullback

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")
DATA_CACHE_PATH = os.path.join(DATA_DIR, "mnq_5m_cache.json")
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
LOG_CSV_PATH = os.path.join(RESULTS_DIR, "log.csv")
SUMMARY_MD_PATH = os.path.join(RESULTS_DIR, "summary.md")
STRATEGY_PARAMS_PATH = os.path.join(REPO_ROOT, "strategy_params.py")

SYMBOL = "MNQ=F"
INTERVAL = "5m"
IN_SAMPLE_FRAC = 0.75
MIN_TRADES = 15  # a candidate's profit factor doesn't count until it's cleared this many closed trades in-sample

# Cycling order for the "one parameter per iteration" search. With the
# default of 10 iterations this touches each parameter once; more
# iterations wrap back around for a second (etc.) refinement pass.
PARAM_ORDER = [
    "adx_low", "adx_high", "trend_fast_len", "trend_slow_len",
    "breakout_window", "vol_mult", "stop_atr_mult",
    "scale_in_atr_mult", "target1_atr_mult", "target2_atr_mult",
]

CANDIDATE_GRID = {
    "adx_low": [10, 15, 20, 25],
    "adx_high": [25, 30, 35, 40],
    "trend_fast_len": [5, 10, 15, 20],
    "trend_slow_len": [30, 50, 75, 100],
    "breakout_window": [1, 2, 3, 5],
    "vol_mult": [1.0, 1.2, 1.4, 1.6, 1.8, 2.0],
    "stop_atr_mult": [0.75, 1.0, 1.25, 1.5, 1.75, 2.0],
    "scale_in_atr_mult": [0.5, 0.75, 1.0, 1.5, 2.0],
    "target1_atr_mult": [0.5, 0.75, 1.0, 1.5],
    "target2_atr_mult": [1.5, 2.0, 2.5, 3.0],
}


# ---------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------
def run_git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=check,
                           capture_output=True, text=True)


def ensure_branch():
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "auto-optimize":
        sys.exit(f"Refusing to run: current branch is '{branch}', must be "
                  f"'auto-optimize'. Run: git checkout auto-optimize")


def ensure_clean_tree():
    status = run_git("status", "--porcelain").stdout.strip()
    if status:
        sys.exit("Refusing to run: working tree has uncommitted changes.\n"
                  f"{status}\nCommit or stash them first, then re-run.")


# ---------------------------------------------------------------------
# Data: fetch once, cache, split chronologically
# ---------------------------------------------------------------------
def load_or_fetch_bars():
    """Returns (bars, freshly_fetched). freshly_fetched is True only when
    this call just wrote a new cache file - the caller must commit it
    before anything else runs, or the working tree stays dirty and every
    subsequent invocation trips ensure_clean_tree()."""
    if os.path.exists(DATA_CACHE_PATH):
        print(f"Using cached data: {DATA_CACHE_PATH} "
              f"(delete this file to force a fresh Yahoo fetch)")
        with open(DATA_CACHE_PATH) as f:
            raw = json.load(f)
        bars = [dict(dt=datetime.fromisoformat(b["dt"]), open=b["open"],
                      high=b["high"], low=b["low"], close=b["close"],
                      volume=b["volume"]) for b in raw]
        return bars, False

    print(f"No cache found - fetching {SYMBOL} {INTERVAL} bars from Yahoo "
          f"(one-time; every iteration after this reuses the cache)...")
    bars = fetch_bars(SYMBOL, INTERVAL)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_CACHE_PATH, "w") as f:
        json.dump([dict(dt=b["dt"].isoformat(), open=b["open"], high=b["high"],
                         low=b["low"], close=b["close"], volume=b["volume"])
                    for b in bars], f)
    print(f"Cached {len(bars)} bars to {DATA_CACHE_PATH}")
    return bars, True


def commit_data_cache(num_bars):
    run_git("add", "data/mnq_5m_cache.json")
    message = (f"auto-optimize: cache {num_bars} MNQ 5m bars from Yahoo\n\n"
               f"Fetched once and committed so every iteration in this (and any "
               f"re-run) optimization pass sees the identical window - Yahoo's "
               f"60-day rolling range would otherwise shift between fetches and "
               f"make iterations incomparable. Delete data/mnq_5m_cache.json and "
               f"re-run to force a fresh fetch.\n")
    run_git("commit", "-m", message)
    print("  committed: data cache")


def split_bars(bars, in_sample_frac=IN_SAMPLE_FRAC):
    split_idx = int(len(bars) * in_sample_frac)
    return bars[:split_idx], bars[split_idx:]


# ---------------------------------------------------------------------
# strategy_params.py read/write
# ---------------------------------------------------------------------
def load_current_params():
    import strategy_params
    return dict(strategy_params.PARAMS), dict(strategy_params.FIXED)


def render_strategy_params(params, fixed):
    lines = [
        '"""',
        "Tunable vwap_pullback parameters - the ONLY file orchestrator.py's",
        "optimization loop is allowed to modify. Regenerated in full on every",
        "iteration that changes a value, so git diff/log shows exactly which",
        "single parameter moved and why (see the matching commit message).",
        '"""',
        "",
        "PARAMS = {",
    ]
    for k in PARAM_ORDER:
        lines.append(f"    {k!r}: {params[k]!r},")
    lines += [
        "}",
        "",
        "# Fixed by design - NEVER changed by the optimization loop. Sizing is an",
        "# account-fit question (PF doesn't move with size, drawdown does - see",
        "# backtest_optimizer.py's sizing-sweep comments); safety rails and cost",
        "# assumptions must never be loosened just to make a run look better.",
        "FIXED = {",
    ]
    for k in sorted(fixed.keys()):
        lines.append(f"    {k!r}: {fixed[k]!r},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_strategy_params(params, fixed):
    with open(STRATEGY_PARAMS_PATH, "w") as f:
        f.write(render_strategy_params(params, fixed))


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------
def score(stats):
    """(profit_factor, net_pnl) tuple, ordered. Disqualifies anything
    under MIN_TRADES by forcing its profit_factor below any real value."""
    if stats["trade_count"] < MIN_TRADES:
        return (-1.0, stats["net_pnl"])
    return (stats["profit_factor"], stats["net_pnl"])


def is_valid_candidate(key, value, current_params):
    """Keeps a mutated key structurally sane relative to its counterpart -
    the backtest will happily run adx_low >= adx_high or a 'fast' EMA
    longer than the 'slow' one, it just won't mean anything."""
    if key == "adx_low":
        return value < current_params["adx_high"]
    if key == "adx_high":
        return value > current_params["adx_low"]
    if key == "trend_fast_len":
        return value < current_params["trend_slow_len"]
    if key == "trend_slow_len":
        return value > current_params["trend_fast_len"]
    return True


# ---------------------------------------------------------------------
# CSV log
# ---------------------------------------------------------------------
CSV_FIELDS = [
    "timestamp", "iteration", "dataset", "parameter", "value", "role",
    "net_pnl", "profit_factor", "max_drawdown", "win_rate", "trade_count",
    "events", "gross_profit", "gross_loss",
    "commission_per_contract", "slippage_ticks", "note",
]


def open_log_writer():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    is_new = not os.path.exists(LOG_CSV_PATH)
    f = open(LOG_CSV_PATH, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    if is_new:
        writer.writeheader()
    return f, writer


def log_row(writer, iteration, dataset, parameter, value, role, stats, note=""):
    writer.writerow({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "iteration": iteration,
        "dataset": dataset,
        "parameter": parameter,
        "value": value,
        "role": role,  # baseline | candidate | selected | final_holdout
        "net_pnl": round(stats["net_pnl"], 2),
        "profit_factor": round(stats["profit_factor"], 4) if stats["profit_factor"] != float("inf") else "inf",
        "max_drawdown": round(stats["max_drawdown"], 2),
        "win_rate": round(stats["win_rate"], 4),
        "trade_count": stats["trade_count"],
        "events": stats["events"],
        "gross_profit": round(stats["gross_profit"], 2),
        "gross_loss": round(stats["gross_loss"], 2),
        "commission_per_contract": 1.0,
        "slippage_ticks": 2,
        "note": note,
    })


# ---------------------------------------------------------------------
# One iteration: mini grid search over exactly one parameter
# ---------------------------------------------------------------------
def run_iteration(iteration_num, current_params, fixed, in_sample_bars, log_writer, forced_key=None):
    key = forced_key if forced_key is not None else PARAM_ORDER[(iteration_num - 1) % len(PARAM_ORDER)]
    candidates = CANDIDATE_GRID[key]
    baseline_value = current_params[key]

    def full_params(value):
        trial = dict(current_params)
        trial[key] = value
        return {**trial, **fixed}

    def evaluate(value, role):
        stats = run_backtest_vwap_pullback(in_sample_bars, SYMBOL, full_params(value))
        log_row(log_writer, iteration_num, "in_sample", key, value, role, stats)
        return stats, score(stats)

    best_value, best_stats = baseline_value, None
    best_stats, best_score = evaluate(baseline_value, "baseline")

    for val in candidates:
        if val == baseline_value or not is_valid_candidate(key, val, current_params):
            continue
        stats, s = evaluate(val, "candidate")
        if s > best_score:
            best_score, best_value, best_stats = s, val, stats

    changed = best_value != baseline_value
    current_params[key] = best_value
    log_row(log_writer, iteration_num, "in_sample", key, best_value, "selected", best_stats,
            note=f"changed from {baseline_value!r}" if changed else "kept baseline, no improvement")

    return key, baseline_value, best_value, changed, best_stats


def commit_iteration(iteration_num, key, old_val, new_val, changed, stats, log_file, current_params, fixed):
    # current_params only changes in memory inside run_iteration() - write it
    # to disk now so strategy_params.py actually reflects this iteration's
    # outcome before it's added/committed (git add on an unwritten file is a
    # silent no-op, which is exactly the bug this guards against).
    write_strategy_params(current_params, fixed)
    # log_file is opened once for the whole run and buffered - flush it to
    # disk before `git add` (a separate process) reads the file, or the
    # just-written rows for this iteration won't be in the commit.
    log_file.flush()
    os.fsync(log_file.fileno())
    run_git("add", "strategy_params.py", "results/log.csv")
    if changed:
        headline = f"auto-optimize: iteration {iteration_num} - {key} {old_val!r} -> {new_val!r}"
        reason = (f"In-sample mini grid-search over {key}'s candidates improved the "
                  f"selection score (profit factor, tie-broken by net P&L, requiring "
                  f">= {MIN_TRADES} in-sample trades).")
    else:
        headline = f"auto-optimize: iteration {iteration_num} - {key} unchanged (no improvement)"
        reason = (f"Mini grid-search over {key}'s candidates found nothing that beat the "
                  f"current value {old_val!r} in-sample (>= {MIN_TRADES} trades required). "
                  f"Left at {old_val!r}.")
    body = (f"{reason}\nIn-sample result at this value: PF={stats['profit_factor']:.3f} "
            f"net=${stats['net_pnl']:.2f} max_drawdown=${stats['max_drawdown']:.2f} "
            f"win_rate={stats['win_rate'] * 100:.1f}% trades={stats['trade_count']}.")
    message = f"{headline}\n\n{body}\n"
    run_git("commit", "-m", message)
    print(f"  committed: {headline}")


# ---------------------------------------------------------------------
# Finalize: confirm the CURRENT strategy_params.py state once on the
# untouched holdout set. Self-contained by design (computes its own
# in-sample stats from current_params/fixed directly, rather than
# depending on in-memory state from a loop in this same process) so it
# works identically whether called at the end of a multi-iteration run
# or standalone via --finalize-only in a later invocation. This relies
# on a real property of run_iteration(): each iteration only applies a
# change when it scores at least as well as the current state in-sample,
# so strategy_params.py's content at any point in time IS the best
# in-sample candidate found so far - there's no separate "best ever
# seen" to track across process boundaries.
# ---------------------------------------------------------------------
def finalize(current_params, fixed, in_sample_bars, holdout_bars, log_writer, log_file, source_note):
    best_params = {**current_params, **fixed}
    in_sample_stats = run_backtest_vwap_pullback(in_sample_bars, SYMBOL, best_params)
    log_row(log_writer, "final", "in_sample", "(final)", "(final)", "final_in_sample", in_sample_stats)

    holdout_stats = run_backtest_vwap_pullback(holdout_bars, SYMBOL, best_params)
    log_row(log_writer, "final", "holdout", "(final)", "(final)", "final_holdout", holdout_stats)

    tunable_final = {k: best_params[k] for k in PARAM_ORDER}
    fixed_final = {k: v for k, v in best_params.items() if k not in PARAM_ORDER}
    write_strategy_params(tunable_final, fixed_final)

    def fmt(stats):
        pf = "inf" if stats["profit_factor"] == float("inf") else f"{stats['profit_factor']:.3f}"
        return (f"PF {pf} \\| net ${stats['net_pnl']:.2f} \\| max DD ${stats['max_drawdown']:.2f} "
                f"\\| win rate {stats['win_rate'] * 100:.1f}% \\| trades {stats['trade_count']} "
                f"\\| events {stats['events']}")

    summary = f"""# auto-optimize: in-sample vs. holdout

Generated by `orchestrator.py` on the `auto-optimize` branch. {source_note}

The holdout figures below are a single, untouched run of this exact config
on the most recent ~{int((1 - IN_SAMPLE_FRAC) * 100)}% of the cached data -
never evaluated until this step. **The holdout result is the honest read,
not the in-sample one.**

## Winning config

```python
PARAMS = {tunable_final!r}
FIXED   = {fixed_final!r}
```

## Results

| Dataset | Metrics |
|---|---|
| In-sample | {fmt(in_sample_stats)} |
| Holdout | {fmt(holdout_stats)} |

## Reading this

- If holdout profit factor is comfortably >= 1.0 and in the same ballpark
  as in-sample, the parameter search found something that generalizes.
- If holdout is much worse than in-sample (or < 1.0 while in-sample
  looked good), the search over-fit to the in-sample window - treat the
  in-sample number as noise, not edge, same standing rule as everywhere
  else in this repo.
- This is still a Python re-implementation on Yahoo data, not a byte-for-
  byte replica of TradingView's fill/PnL accounting - confirm any
  candidate worth pursuing in TradingView's own Strategy Tester before it
  goes anywhere near `pinescript/jarvis_vwap_pullback_mnq.pine` or a live
  account.
"""
    with open(SUMMARY_MD_PATH, "w") as f:
        f.write(summary)

    log_file.flush()
    os.fsync(log_file.fileno())
    run_git("add", "strategy_params.py", "results/log.csv", "results/summary.md")
    message = (f"auto-optimize: finalize current candidate, confirm on holdout\n\n"
               f"{source_note} Holdout (never touched until now): "
               f"PF={holdout_stats['profit_factor']:.3f} net=${holdout_stats['net_pnl']:.2f} "
               f"max_drawdown=${holdout_stats['max_drawdown']:.2f} "
               f"win_rate={holdout_stats['win_rate'] * 100:.1f}% "
               f"trades={holdout_stats['trade_count']}. See results/summary.md.\n")
    run_git("commit", "-m", message)
    print(f"  committed: finalize + holdout confirmation")
    return holdout_stats


# ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iterations", type=int, default=10,
                         help="how many parameters to cycle through (default 10, one full pass). "
                              "Ignored if --param is given (that always runs exactly one targeted search).")
    parser.add_argument("--param", choices=PARAM_ORDER, default=None,
                         help="search exactly this one parameter instead of cycling the fixed order - "
                              "for an agent/human directing the search one targeted step at a time.")
    parser.add_argument("--finalize-only", action="store_true",
                         help="skip the search entirely and just confirm the CURRENT strategy_params.py "
                              "state once on the untouched holdout set (writes results/summary.md).")
    parser.add_argument("--push", action="store_true", help="push the auto-optimize branch after finishing")
    args = parser.parse_args()

    ensure_branch()
    ensure_clean_tree()

    bars, freshly_fetched = load_or_fetch_bars()
    if len(bars) < 300:
        sys.exit(f"Only {len(bars)} bars available - not enough for a meaningful split. Aborting.")
    if freshly_fetched:
        commit_data_cache(len(bars))
    in_sample_bars, holdout_bars = split_bars(bars)
    print(f"Total bars: {len(bars)} ({bars[0]['dt'].date()} to {bars[-1]['dt'].date()})")
    print(f"In-sample:  {len(in_sample_bars)} bars ({in_sample_bars[0]['dt'].date()} to {in_sample_bars[-1]['dt'].date()})")
    print(f"Holdout:    {len(holdout_bars)} bars ({holdout_bars[0]['dt'].date()} to {holdout_bars[-1]['dt'].date()}) - untouched until the final step")

    current_params, fixed = load_current_params()
    log_file, log_writer = open_log_writer()

    try:
        if args.finalize_only:
            # The only path that touches holdout - a deliberate, explicit call,
            # never an automatic side effect of a targeted --param search.
            print(f"\n--finalize-only: confirming the current strategy_params.py state on the untouched holdout set...")
            source_note = "Confirming the current strategy_params.py state (--finalize-only, no search run this invocation)."
            holdout_stats = finalize(current_params, fixed, in_sample_bars, holdout_bars, log_writer, log_file, source_note)
            print(f"Holdout: PF={holdout_stats['profit_factor']:.3f} net=${holdout_stats['net_pnl']:.2f} "
                  f"max_drawdown=${holdout_stats['max_drawdown']:.2f} "
                  f"win_rate={holdout_stats['win_rate'] * 100:.1f}% trades={holdout_stats['trade_count']}")
            print(f"\nSee results/summary.md and results/log.csv for full detail.")
        elif args.param:
            # A single targeted step, meant to be called repeatedly (e.g. by an
            # agent directing the search). Never touches holdout - only
            # --finalize-only does that, deliberately, once.
            print(f"\nTargeted search: {args.param}")
            key, old_val, new_val, changed, stats = run_iteration(
                1, current_params, fixed, in_sample_bars, log_writer, forced_key=args.param)
            verb = "changed" if changed else "kept (no improvement)"
            print(f"  {key}: {old_val!r} -> {new_val!r} ({verb})  "
                  f"PF={stats['profit_factor']:.3f} net=${stats['net_pnl']:.2f} "
                  f"max_drawdown=${stats['max_drawdown']:.2f} win_rate={stats['win_rate'] * 100:.1f}% "
                  f"trades={stats['trade_count']}")
            commit_iteration(1, key, old_val, new_val, changed, stats, log_file, current_params, fixed)
        else:
            # Default: one full pass through the fixed parameter order, then
            # finalize - the original, standalone behavior.
            for i in range(1, args.iterations + 1):
                print(f"\nIteration {i}/{args.iterations}:")
                key, old_val, new_val, changed, stats = run_iteration(
                    i, current_params, fixed, in_sample_bars, log_writer)
                verb = "changed" if changed else "kept (no improvement)"
                print(f"  {key}: {old_val!r} -> {new_val!r} ({verb})  "
                      f"PF={stats['profit_factor']:.3f} net=${stats['net_pnl']:.2f} "
                      f"trades={stats['trade_count']}")
                commit_iteration(i, key, old_val, new_val, changed, stats, log_file, current_params, fixed)

            print(f"\nFinalizing: confirming the current strategy_params.py state on the untouched holdout set...")
            source_note = f"Confirming the state after {args.iterations} iteration(s) this run (last: `{key}` -> {new_val!r})."
            holdout_stats = finalize(current_params, fixed, in_sample_bars, holdout_bars, log_writer, log_file, source_note)
            print(f"Holdout: PF={holdout_stats['profit_factor']:.3f} net=${holdout_stats['net_pnl']:.2f} "
                  f"max_drawdown=${holdout_stats['max_drawdown']:.2f} "
                  f"win_rate={holdout_stats['win_rate'] * 100:.1f}% trades={holdout_stats['trade_count']}")
            print(f"\nSee results/summary.md and results/log.csv for full detail.")
    finally:
        log_file.close()

    if args.push:
        print("\nPushing auto-optimize branch...")
        run_git("push", "-u", "origin", "auto-optimize")
        print("Pushed.")
    else:
        print("\nNot pushed (default). Review `git log` on auto-optimize, then "
              "`git push -u origin auto-optimize` when you're satisfied, "
              "or re-run with --push next time.")


if __name__ == "__main__":
    main()
