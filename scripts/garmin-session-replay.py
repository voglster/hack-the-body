"""Replay user's Garmin Connect browser session against connectapi paths.

Authorized one-shot: pull the user's own data from Garmin using their existing
authenticated browser session (cookies + CSRF), with TLS impersonation so
Cloudflare doesn't fingerprint-block the request.

This is a stopgap until the ingestor is migrated to a real-browser auth flow
(Playwright/SeleniumBase). It exists because the standard `garth` SSO route
is blocked by Garmin's Cloudflare WAF on residential IPs.

Usage:
  1. Open https://connect.garmin.com/modern/ in Brave.
  2. F12 -> Network -> filter `connectapi` -> right-click any XHR ->
     Copy as cURL.
  3. Paste the cookie/header values from that cURL into BROWSER_COOKIES /
     BROWSER_HEADERS below, replacing the placeholders.
  4. Run from a venv that has curl-cffi installed:
       python scripts/garmin-session-replay.py
  5. Pipe the JSON output to scripts/import-to-mongo.py (TODO) to load
     into the data spine.

Cookie/JWT lifetime is short — JWT_WEB typically expires in ~30 min.
Re-paste fresh values whenever they expire.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from curl_cffi import requests

# ---------------------------------------------------------------------------
# Replace these with values from your DevTools "Copy as cURL" snippet.
# Keep this file out of version control if you fill in real values
# (it's gitignored by default — see .gitignore at the project root for the
# rule covering scripts/garmin-session-*).
# ---------------------------------------------------------------------------

BROWSER_COOKIES: dict[str, str] = {
    "GARMIN-SSO": "1",
    "GARMIN-SSO-CUST-GUID": "REPLACE_ME",
    "_cfuvid": "REPLACE_ME",
    "JWT_WEB": "REPLACE_ME",
    "SESSIONID": "REPLACE_ME",
    "__cflb": "REPLACE_ME",
}

BROWSER_HEADERS: dict[str, str] = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.6",
    "connect-csrf-token": "REPLACE_ME",
    "nk": "NT",
    "sec-ch-ua": '"Brave";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-gpc": "1",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "x-app-ver": "5.24.1.1",
    "x-lang": "en-US",
    "referer": "https://connect.garmin.com/modern/",
}

BASE = "https://connect.garmin.com/gc-api"
IMPERSONATE = "chrome131"


def _check_filled() -> None:
    bad = [k for k, v in BROWSER_COOKIES.items() if v == "REPLACE_ME"]
    bad += [
        f"header:{k}" for k, v in BROWSER_HEADERS.items() if v == "REPLACE_ME"
    ]
    if bad:
        print(
            "Fill in the REPLACE_ME values from your DevTools Copy-as-cURL:\n  - "
            + "\n  - ".join(bad),
            file=sys.stderr,
        )
        sys.exit(2)


def get(path: str) -> requests.Response:
    return requests.get(
        BASE + path,
        cookies=BROWSER_COOKIES,
        headers=BROWSER_HEADERS,
        impersonate=IMPERSONATE,
        timeout=15,
    )


def main() -> int:
    _check_filled()

    print("=== whoami (socialProfile) ===")
    r = get("/userprofile-service/socialProfile")
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  body[:400]: {r.text[:400]}")
        return 1
    profile = r.json()
    user_name = profile.get("userName") or profile.get("displayName")
    print(f"  displayName: {profile.get('displayName')}")
    print(f"  userName: {user_name}")
    print(f"  fullName: {profile.get('fullName')}")
    print()

    if not user_name:
        print("could not determine username; aborting", file=sys.stderr)
        return 1

    today = date.today()
    start = today - timedelta(days=14)

    endpoints = {
        "weight": f"/weight-service/weight/range/{start.isoformat()}/{today.isoformat()}?includeAll=true",
        "vo2max": f"/userstats-service/wellness/daily/{user_name}?fromDate={start.isoformat()}&untilDate={today.isoformat()}",
        "workouts": f"/activitylist-service/activities/search/activities?startDate={start.isoformat()}&endDate={today.isoformat()}&limit=200",
        "sleep_today": f"/wellness-service/wellness/dailySleepData/{user_name}?date={today.isoformat()}",
        "hrv_today": f"/hrv-service/hrv/{today.isoformat()}",
    }

    out: dict[str, object] = {"profile": profile}
    for name, path in endpoints.items():
        r = get(path)
        print(f"  {name}: HTTP {r.status_code}")
        try:
            out[name] = r.json() if r.status_code == 200 else {"_error_status": r.status_code, "_body": r.text[:200]}
        except Exception:
            out[name] = {"_unparseable": True, "_body": r.text[:200]}

    out_path = "/tmp/garmin-replay.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nDumped to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
