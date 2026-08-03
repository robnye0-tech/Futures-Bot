"""
Local read-only status dashboard for the trading strategy.

Run this in a separate terminal from strategy.py (it reads the shared
runtime_state.json file that the strategy writes to - it does not place
trades itself).
"""

from dotenv import load_dotenv
from flask import Flask, render_template

import shared_state
from config import DASHBOARD_PORT

load_dotenv()

app = Flask(__name__)


@app.route("/")
def overview():
    state = shared_state.load_state()
    return render_template("overview.html", state=state, active_tab="overview")


@app.route("/positions")
def positions():
    state = shared_state.load_state()
    return render_template("positions.html", state=state, active_tab="positions")


@app.route("/log")
def trade_log():
    state = shared_state.load_state()
    entries = list(reversed(state.get("trade_log", [])))
    return render_template("log.html", state=state, entries=entries, active_tab="log")


@app.route("/news")
def news():
    state = shared_state.load_state()
    return render_template("news.html", state=state, active_tab="news")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=DASHBOARD_PORT, debug=False)
