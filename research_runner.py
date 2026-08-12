"""
Scheduled wrapper around backtest_optimizer.py.

Runs the exact same walk-forward search as `python backtest_optimizer.py`,
but also appends the output to a timestamped, permanent log file
(research_log.txt) instead of only printing to the console - so results
accumulate across runs over time. This is "option 1" from the README's
"Getting a longer backtest window" section: Yahoo Finance caps 5m/15m data
at 60 days per pull, so the way to build up a longer real track record for
free is letting time pass and re-running periodically, then comparing
whether the same candidates keep holding up across separately-drawn
windows - not any single big pull.

Run manually:

    python research_runner.py

Or schedule it (e.g. Windows Task Scheduler, weekly) instead of running
backtest_optimizer.py directly - see README for the exact schtasks/
Register-ScheduledTask command.

IMPORTANT - what this does NOT do: it does not touch TradingView, does
not create/edit/deploy any Pine Script, and does not place or suggest
any trade automatically. It only re-runs the same local Python research
search on fresh data and logs the result for you to read. Any candidate
that looks promising here still needs the same manual TradingView
Strategy Tester confirmation (profit factor, trade count, max drawdown
vs. the real $2,000 account limit) every other result in this repo has
gone through before it's trusted.
"""

import contextlib
import io
from datetime import datetime, timezone

import backtest_optimizer as bo

LOG_PATH = "research_log.txt"


def main():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bo.main()
    output = buf.getvalue()

    print(output)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n{'#' * 70}\n# Research run: {timestamp}\n{'#' * 70}\n")
        f.write(output)
        f.write("\n")

    print(f"\nAppended this run to {LOG_PATH} - compare against earlier "
          f"runs to see which candidates keep holding up over time.")


if __name__ == "__main__":
    main()
