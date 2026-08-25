# Backlog — safety hardening and nice-to-haves

Ideas raised while dialing in `jarvis_vwap_pullback_mnq.pine`, written down so
they don't just live in chat history. Nothing here is built yet. None of this
should be implemented reactively/urgently - same rule as everything else in
this repo: design it, test it (Python walk-forward and/or a controlled
TradingView A/B), confirm it doesn't regress the current confirmed baseline,
before it ever becomes a live default.

## Still open, more urgent than "backlog" (do before real money is at risk)

- **Daily Kill Switch is still a placeholder.** The input `dailyKillUSD`
  defaults to `900` with a label admitting it's a placeholder. Now that the
  real $150K account numbers are known ($3,000 daily loss limit, $5,250 EOD
  trailing drawdown), this needs to become a real, deliberately-chosen number
  with a safety margin under $3,000 - not the leftover placeholder. This
  isn't a "someday" item, it's a "before this account goes live" item.

## Safety / risk-protection ideas

1. **Cumulative trailing-drawdown kill switch, not just a daily one.**
   The current kill switch only resets and measures loss *within a single
   day*. Tradeify's real rule is an EOD *trailing* drawdown from the
   account's peak equity - several days of losses, each individually under
   the daily kill threshold, could still add up to breach the trailing
   limit without ever tripping today's kill switch. A second switch that
   tracks running peak equity since account start (or since last reset) and
   halts trading once drawdown from that peak crosses a threshold would
   protect against the rule that can actually end the account.

2. **A hard sanity ceiling on position size, independent of the input box.**
   Right now nothing stops a typo in Base Size (e.g. `80` instead of `8`)
   from being accepted and traded. A simple `if baseSize > <some sane max>:
   don't trade, throw a visible warning` check would catch a fat-fingered
   input before it reaches a live order.

3. **Max trades per day circuit breaker.** A hard cap (e.g. "if more than N
   entries have fired today, stop taking new ones") as a backstop against
   any future logic bug that could cause runaway repeated entries - cheap
   insurance, not expected to ever actually bind under normal conditions.

4. **Scheduled high-impact news blackout.** Optionally suppress new entries
   in a window around scheduled high-impact releases (CPI, FOMC, NFP) that
   can produce abnormal volatility/gaps outside what the backtested edge
   was ever tested against. Would need a maintained calendar source or a
   simple manual date/time blackout list.

5. **Connectivity / heartbeat check.** A way to notice if TradingView, the
   PickMyTrade bridge, or the broker connection silently drops mid-session -
   e.g. an alert if no expected bar update arrives for X minutes during
   market hours - so a dropped connection with an open position doesn't go
   unnoticed.

6. **Consistency-rule (20%) awareness.** Not a trading halt, just a status
   readout: flag when a single day's profit is approaching 20% of the
   account's total profit-to-date, since that affects payout eligibility
   even though it doesn't affect account survival. Purely informational.

## Nice-to-have / performance ideas (not safety-critical)

7. **Trailing stop or faster profit-lock on unusually strong moves** —
   already on the "maybe" pile from earlier: either let winners run further
   past the current fixed 2.0x-ATR T2, or lock in an earlier partial when
   price moves an abnormal amount very quickly. Two different mechanisms,
   would need to be designed and tested separately.

8. **Trade/alert notifications to phone.** Wire TradingView alerts to push
   notification, SMS, or email on every entry/exit so trades are visible in
   real time without watching the chart.

9. **Automated daily/weekly performance log.** Something like
   `research_runner.py`'s logging pattern, but for actual trade results
   instead of backtest research runs - a running record of real performance
   over time, separate from whatever TradingView's own history shows.

10. **Multi-timeframe validation** (already discussed, deliberately not
    started yet): walk-forward test additional timeframes (1m, 3m, 10m,
    30m, 1h) the same rigorous way 5m was validated, before ever enabling
    them in the `tfValidated` gate.

11. **Multi-account scaling within Tradeify.** Once a single account proves
    out live, replicate across up to 5 Tradeify accounts (per their plan
    limit) for more aggregate capacity - not diversification, since every
    account fires the same signals at the same time (see chat notes on
    this). Confirmed compatible with Tradeify's bot policy as long as every
    account stays within Tradeify (using the same bot across multiple
    *firms* is against their terms).

12. **ORB + VWAP retest strategy** (`research_orb_retest.py`) - separate
    side research track, still fully untested. Not part of this list's
    scope beyond noting it exists and isn't forgotten.
