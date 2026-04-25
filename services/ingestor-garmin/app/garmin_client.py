from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import garth
from garth.exc import GarthHTTPError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class GarminRateLimitError(RuntimeError):
    """Raised when Garmin SSO returns 429. Caller should back off for many minutes."""


class GarminClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session_dir = Path(settings.garmin_session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def login(self) -> None:
        # Prefer cached session: if it works, never touch SSO.
        if self._resume_ok():
            return
        if not self.settings.garmin_email or not self.settings.garmin_password:
            raise RuntimeError(
                "no cached Garmin session and GARMIN_EMAIL/GARMIN_PASSWORD not set"
            )
        try:
            garth.login(self.settings.garmin_email, self.settings.garmin_password)
        except GarthHTTPError as e:
            status = getattr(getattr(e, "error", None), "response", None)
            if status is not None and status.status_code == 429:
                raise GarminRateLimitError(
                    "Garmin SSO rate-limited (429). Back off >=30min."
                ) from e
            raise
        garth.save(str(self.session_dir))

    def _resume_ok(self) -> bool:
        try:
            garth.resume(str(self.session_dir))
            _ = garth.client.username
            return True
        except Exception:
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _get(self, path: str) -> dict | list:
        return garth.connectapi(path)

    def fetch_sleep(self, day: date) -> dict:
        return self._get(f"/wellness-service/wellness/dailySleepData/{garth.client.username}?date={day.isoformat()}")

    def fetch_hrv(self, day: date) -> dict:
        return self._get(f"/hrv-service/hrv/{day.isoformat()}")

    def fetch_weight(self, start: date, end: date) -> list[dict]:
        data = self._get(
            f"/weight-service/weight/range/{start.isoformat()}/{end.isoformat()}?includeAll=true"
        )
        return data.get("dateWeightList", []) if isinstance(data, dict) else data

    def fetch_body_comp(self, start: date, end: date) -> list[dict]:
        return self.fetch_weight(start, end)

    def fetch_vo2max(self, day: date) -> dict:
        return self._get(
            f"/userstats-service/wellness/daily/{garth.client.username}?fromDate={day.isoformat()}&untilDate={day.isoformat()}"
        )

    def fetch_workouts(self, start: date, end: date) -> list[dict]:
        return self._get(
            f"/activitylist-service/activities/search/activities?startDate={start.isoformat()}&endDate={end.isoformat()}&limit=200"
        )

    def fetch_rhr_series(self, start: date, end: date) -> list[dict]:
        return self._get(
            f"/userstats-service/wellness/daily/summary?fromDate={start.isoformat()}&untilDate={end.isoformat()}"
        )


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def backfill_window(days: int) -> tuple[date, date]:
    end = today_utc()
    start = end - timedelta(days=days)
    return start, end
