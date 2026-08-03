"""
Fetches headlines relevant to the Nasdaq/NQ (mega-cap tech + macro drivers)
from Alpha Vantage's News & Sentiment API.

Free API key: https://www.alphavantage.co/support/#api-key
Free tier is rate-limited, so this is meant to be called on a timer
(see NEWS_REFRESH_MINUTES in config.py), not on every strategy iteration.
"""

import os

import requests

from config import NEWS_TICKERS, NEWS_TOPICS

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"


def fetch_relevant_news(limit=15):
    """Returns a list of headline dicts, or [] if unavailable (missing key, rate limited, network error)."""
    if not ALPHAVANTAGE_API_KEY:
        return []

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": NEWS_TICKERS,
        "topics": NEWS_TOPICS,
        "sort": "LATEST",
        "limit": str(limit),
        "apikey": ALPHAVANTAGE_API_KEY,
    }

    try:
        resp = requests.get(ALPHAVANTAGE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    if "Information" in data or "Note" in data:
        # Rate limited or bad key - Alpha Vantage returns 200 with an explanatory
        # message instead of an HTTP error in these cases.
        return []

    headlines = []
    for item in data.get("feed", [])[:limit]:
        headlines.append({
            "title": item.get("title"),
            "source": item.get("source"),
            "url": item.get("url"),
            "time_published": item.get("time_published"),
            "sentiment_label": item.get("overall_sentiment_label"),
            "sentiment_score": item.get("overall_sentiment_score"),
        })
    return headlines
