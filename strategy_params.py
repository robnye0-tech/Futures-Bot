"""
Tunable vwap_pullback parameters - the ONLY file orchestrator.py's
optimization loop is allowed to modify. Regenerated in full on every
iteration that changes a value, so git diff/log shows exactly which
single parameter moved and why (see the matching commit message).

Seeded from backtest_optimizer.py's LIVE_CONFIG (the exact settings
live in jarvis_vwap_pullback_mnq.pine as of this branch's creation).
"""

PARAMS = {
    'adx_low': 15,
    'adx_high': 30,
    'trend_fast_len': 10,
    'trend_slow_len': 50,
    'breakout_window': 1,
    'vol_mult': 1.6,
    'stop_atr_mult': 1.5,
    'scale_in_atr_mult': 1.0,
    'target1_atr_mult': 1.0,
    'target2_atr_mult': 2.0,
}

# Fixed by design - NEVER changed by the optimization loop. Sizing is an
# account-fit question (PF doesn't move with size, drawdown does - see
# backtest_optimizer.py's sizing-sweep comments); safety rails and cost
# assumptions must never be loosened just to make a run look better.
FIXED = {
    'add_size': 0,
    'base_size': 7,
    'cumulative_kill_persists': False,
    'cumulative_kill_usd': 4000,
    'daily_kill_usd': 2200,
    'force_flat_time': (16, 59),
    'max_size': 7,
}
