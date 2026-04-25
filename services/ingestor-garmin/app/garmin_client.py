from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class GarminRateLimitError(RuntimeError):
    """Garmin SSO returned 429. Caller should back off and try a different IP."""


class GarminClient:
    """Wraps `garminconnect` (which wraps garth + curl-cffi for TLS impersonation).

    Login policy:
    1. Try to resume a cached session from disk. If valid, never touch SSO.
    2. Only on first run / expired session, attempt login with credentials.
    3. On 429, raise GarminRateLimitError so the caller can log it cleanly.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session_dir = Path(settings.garmin_session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._g: Garmin | None = None

    def login(self) -> None:
        # Build a Garmin instance without credentials so we can try resume first.
        g = Garmin()
        try:
            g.login(str(self.session_dir))  # garminconnect supports passing token dir to skip login
            self._g = g
            return
        except Exception:
            pass

        # No cached session (or expired). Need creds.
        if not self.settings.garmin_email or not self.settings.garmin_password:
            raise RuntimeError(
                "no cached Garmin session and GARMIN_EMAIL/GARMIN_PASSWORD not set"
            )

        g = Garmin(email=self.settings.garmin_email, password=self.settings.garmin_password)
        try:
            g.login()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                raise GarminRateLimitError(
                    "Garmin SSO rate-limited (429). Different egress IP required."
                ) from e
            raise
        # Persist tokens for next time.
        g.garth.dump(str(self.session_dir))
        self._g = g

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _connectapi(self, path: str) -> Any:
        assert self._g is not None, "login() must be called first"
        return self._g.connectapi(path)

    @property
    def _username(self) -> str:
        assert self._g is not None
        return self._g.garth.username

    def fetch_sleep(self, day: date) -> dict:
        return self._connectapi(
            f"/wellness-service/wellness/dailySleepData/{self._username}?date={day.isoformat()}"
        )

    def fetch_hrv(self, day: date) -> dict:
        return self._connectapi(f"/hrv-service/hrv/{day.isoformat()}")

    def fetch_weight(self, start: date, end: date) -> list[dict]:
        data = self._connectapi(
            f"/weight-service/weight/range/{start.isoformat()}/{end.isoformat()}?includeAll=true"
        )
        return data.get("dateWeightList", []) if isinstance(data, dict) else data

    def fetch_body_comp(self, start: date, end: date) -> list[dict]:
        return self.fetch_weight(start, end)

    def fetch_vo2max(self, day: date) -> dict:
        return self._connectapi(
            f"/userstats-service/wellness/daily/{self._username}"
            f"?fromDate={day.isoformat()}&untilDate={day.isoformat()}"
        )

    def fetch_workouts(self, start: date, end: date) -> list[dict]:
        return self._connectapi(
            f"/activitylist-service/activities/search/activities"
            f"?startDate={start.isoformat()}&endDate={end.isoformat()}&limit=200"
        )

    def fetch_rhr_series(self, start: date, end: date) -> list[dict]:
        return self._connectapi(
            f"/userstats-service/wellness/daily/summary"
            f"?fromDate={start.isoformat()}&untilDate={end.isoformat()}"
        )


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def backfill_window(days: int) -> tuple[date, date]:
    end = today_utc()
    start = end - timedelta(days=days)
    return start, end
