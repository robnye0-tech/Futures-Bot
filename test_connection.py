"""
Standalone Tradovate connection test - authenticates and lists accounts.

Places ZERO orders. This exists purely to verify your credentials in .env
are correct before running the real strategy. Run this first, always.

Usage:
    python test_connection.py
"""

import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("TRADOVATE_USERNAME")
PASSWORD = os.getenv("TRADOVATE_DEDICATED_PASSWORD")
CID = os.getenv("TRADOVATE_CID")
SECRET = os.getenv("TRADOVATE_SECRET")
IS_PAPER = os.getenv("TRADOVATE_IS_PAPER", "true").lower() == "true"

# These may have been assigned specific values when Tradovate approved your
# API access - check your approval email/dashboard. These are placeholders.
APP_ID = os.getenv("TRADOVATE_APP_ID", "Jarvis Futures Bot")
APP_VERSION = os.getenv("TRADOVATE_APP_VERSION", "1.0")

BASE_URL = "https://demo.tradovateapi.com/v1" if IS_PAPER else "https://live.tradovateapi.com/v1"


def main():
    missing = [name for name, val in [
        ("TRADOVATE_USERNAME", USERNAME),
        ("TRADOVATE_DEDICATED_PASSWORD", PASSWORD),
        ("TRADOVATE_CID", CID),
        ("TRADOVATE_SECRET", SECRET),
    ] if not val]
    if missing:
        print(f"Missing from .env: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your real credentials first.")
        sys.exit(1)

    print(f"Connecting to {'DEMO' if IS_PAPER else 'LIVE'} environment: {BASE_URL}")

    auth_payload = {
        "name": USERNAME,
        "password": PASSWORD,
        "appId": APP_ID,
        "appVersion": APP_VERSION,
        "cid": CID,
        "sec": SECRET,
        "deviceId": str(uuid.uuid4()),
    }

    resp = requests.post(
        f"{BASE_URL}/auth/accesstokenrequest",
        json=auth_payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=15,
    )

    try:
        data = resp.json()
    except ValueError:
        print(f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:500]}")
        sys.exit(1)

    if resp.status_code != 200 or data.get("errorText"):
        print(f"AUTH FAILED (HTTP {resp.status_code}): {data.get('errorText', data)}")
        print("\nCommon causes: wrong dedicated password (not your login password), "
              "wrong CID/secret, or appId/appVersion not matching what Tradovate approved.")
        sys.exit(1)

    access_token = data.get("accessToken")
    print(f"AUTH SUCCESS - user: {data.get('name')}, userId: {data.get('userId')}, "
          f"hasLive: {data.get('hasLive')}")

    # Confirm the token actually works with an authenticated read-only call.
    accounts_resp = requests.get(
        f"{BASE_URL}/account/list",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if accounts_resp.status_code != 200:
        print(f"Auth succeeded but account list failed (HTTP {accounts_resp.status_code}): "
              f"{accounts_resp.text[:500]}")
        sys.exit(1)

    accounts = accounts_resp.json()
    print(f"\nFound {len(accounts)} account(s):")
    for acct in accounts:
        print(f"  - id={acct.get('id')} name={acct.get('name')} "
              f"active={acct.get('active')} accountType={acct.get('accountType')}")

    print("\nConnection test passed. No orders were placed.")


if __name__ == "__main__":
    main()
