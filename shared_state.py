"""
Tiny file-based state store shared between the trading strategy process
and the dashboard process. The strategy writes, the dashboard reads.

Not a database - this is intentionally simple for a single-user local setup.
Writes are atomic (write to a temp file, then os.replace) so the dashboard
never reads a half-written file.
"""

import json
import os
from datetime import datetime

from config import STATE_FILE


def _default_state():
    return {
        "last_updated": None,
        "trading_day": None,
        "daily_start_equity": None,
        "portfolio_value": None,
        "daily_pnl": None,
        "daily_halted": False,
        "positions": {},
        "trade_log": [],
        "news": [],
        "news_last_fetched": None,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        merged = _default_state()
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return _default_state()


def save_state(state):
    state["last_updated"] = datetime.now().isoformat(timespec="seconds")
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp_path, STATE_FILE)


def update_state(**kwargs):
    state = load_state()
    state.update(kwargs)
    save_state(state)
    return state


def append_trade_log(entry, max_entries=200):
    state = load_state()
    log = state.get("trade_log", [])
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    log.append(entry)
    state["trade_log"] = log[-max_entries:]
    save_state(state)


def set_positions(positions):
    state = load_state()
    state["positions"] = positions
    save_state(state)


def set_news(news_items):
    state = load_state()
    state["news"] = news_items
    state["news_last_fetched"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
