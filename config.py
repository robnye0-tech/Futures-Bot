"""Shared configuration for the strategy and dashboard."""

import os

SYMBOLS = ["MNQ", "MES"]

BASE_SIZE = 3          # initial contracts per entry
MAX_SIZE = 9            # hard cap per symbol (well under Tradeify's 40-micro limit)
ADD_INCREMENT = 3       # contracts added per successful scale-in step

FAST_EMA = 9
SLOW_EMA = 21
ATR_PERIOD = 14
VOLUME_LOOKBACK = 20
VOLUME_MULTIPLIER = 1.5   # current volume must exceed this x the rolling average

STOP_ATR_MULT = 1.5        # initial stop distance = 1.5x ATR
SCALE_IN_ATR_MULT = 1.0    # price must move 1x ATR in favor before adding
TARGET_1_ATR_MULT = 1.0    # first partial profit target
TARGET_2_ATR_MULT = 2.0    # second partial profit target

# --- Risk limits: PLACEHOLDERS pending confirmation of the real Tradeify numbers ---
RISK_PER_TRADE_USD = 250
DAILY_KILL_SWITCH_USD = 900   # must stay below Tradeify's $1,250 daily loss limit

SESSION_START_HOUR, SESSION_START_MIN = 9, 30
SESSION_END_HOUR, SESSION_END_MIN = 16, 0

NEWS_REFRESH_MINUTES = 30
NEWS_TOPICS = "technology,financial_markets,economy_macro,economy_monetary"
NEWS_TICKERS = "QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "runtime_state.json")

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
