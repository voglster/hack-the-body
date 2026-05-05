from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class GarminRateLimitError(RuntimeError):
    """Garmin SSO returned 429. Caller should back off and try a different IP."""


class GarminClient:
    """Wraps `garminconnect` 0.3.x.

    Auth model:
    1. `garminconnect` accepts a `tokenstore` directory holding `garmin_tokens.json`.
    2. If tokens exist, library loads them. If the DI access token is near expiry,
       it refreshes silently via the DI refresh endpoint (NOT Cloudflare-blocked SSO).
    3. Only on cold-start with no tokens does it run the 5-strategy SSO chain.
    4. After any successful login, library writes tokens back to disk for the next run.

    First-run bootstrap: run `garmin-login` from a clean IP once, copy the resulting
    `garmin_tokens.json` into the configured session dir on the prod host. From then
    on the ingestor refreshes itself and never touches SSO again.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session_dir = Path(settings.garmin_session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._g: Garmin | None = None

    def login(self) -> None:
        # Pass credentials so SSO can run as a fallback. Tokenstore takes priority:
        # if tokens exist there, library loads + refreshes them and skips SSO.
        g = Garmin(
            email=self.settings.garmin_email or None,
            password=self.settings.garmin_password or None,
        )
        try:
            g.login(tokenstore=str(self.session_dir))
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                raise GarminRateLimitError(
                    "Garmin SSO rate-limited (429). Bootstrap tokens from a clean IP."
                ) from e
            raise
        self._g = g

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _connectapi(self, path: str) -> Any:
        if self._g is None:
            raise RuntimeError("login() must be called first")
        return self._g.connectapi(path)

    @property
    def _username(self) -> str:
        if self._g is None:
            raise RuntimeError("login() must be called first")
        return self._g.display_name

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
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        # Current schema: { dailyWeightSummaries: [ { allWeightMetrics: [...] } ] }
        # Legacy schema: { dateWeightList: [...] }
        if "dailyWeightSummaries" in data:
            out: list[dict] = []
            seen: set = set()
            for day in data.get("dailyWeightSummaries") or []:
                for m in day.get("allWeightMetrics") or []:
                    pk = m.get("samplePk")
                    if pk in seen:
                        continue
                    if pk is not None:
                        seen.add(pk)
                    out.append(m)
            return out
        return data.get("dateWeightList", [])

    def fetch_body_comp(self, start: date, end: date) -> list[dict]:
        return self.fetch_weight(start, end)

    def fetch_vo2max(self, day: date) -> dict:
        return self._connectapi(
            f"/userstats-service/wellness/daily/{self._username}"
            f"?fromDate={day.isoformat()}&untilDate={day.isoformat()}"
        )

    def fetch_workouts(self, start: date, end: date) -> list[dict]:
        # Paginate. Garmin caps each page at 200; iterate via &start= until
        # a short page comes back. Otherwise duplicate-flood cleanup misses
        # everything past activity #200.
        out: list[dict] = []
        page_size = 200
        offset = 0
        while True:
            page = self._connectapi(
                f"/activitylist-service/activities/search/activities"
                f"?startDate={start.isoformat()}&endDate={end.isoformat()}"
                f"&start={offset}&limit={page_size}"
            )
            if not isinstance(page, list) or not page:
                break
            out.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return out

    def fetch_rhr_series(self, start: date, end: date) -> list[dict]:
        return self._connectapi(
            f"/userstats-service/wellness/daily/summary"
            f"?fromDate={start.isoformat()}&untilDate={end.isoformat()}"
        )

    def fetch_intraday_steps(self, day: date) -> list[dict]:
        """Garmin's 15-minute step buckets for a day.

        Returns a list of `{startGMT, endGMT, steps, primaryActivityLevel}`
        records spanning the day. Empty list if nothing's been synced yet.
        """
        data = self._connectapi(
            f"/wellness-service/wellness/dailySummaryChart/{self._username}"
            f"?date={day.isoformat()}",
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("wellnessSteps") or data.get("steps") or []
        return []

    def fetch_daily_summary(self, day: date) -> dict:
        """Garmin's rich per-day wellness summary: steps, distance, calories,
        resting HR, intensity minutes, floors, etc."""
        return self._connectapi(
            f"/usersummary-service/usersummary/daily/{self._username}"
            f"?calendarDate={day.isoformat()}"
        )

    def upload_tcx(self, tcx_bytes: bytes, *, name_hint: str) -> dict:
        """Upload a TCX activity. Returns Garmin's response dict (contains
        the new `activityId` on success, or signals 409 duplicate)."""
        if self._g is None:
            raise RuntimeError("login() must be called first")
        # garminconnect.upload_activity reads from a file path, so write
        # to a tmpfile first.
        import tempfile  # noqa: PLC0415
        with tempfile.NamedTemporaryFile(
            suffix=".tcx", prefix=f"{name_hint}-", delete=False,
        ) as f:
            f.write(tcx_bytes)
            path = f.name
        return self._g.upload_activity(path)

    def set_activity_type_walking(self, activity_id: int | str) -> Any:
        """Re-classify a freshly-uploaded activity as 'walking' on Garmin Connect.

        TCX has no Walking sport, so we upload as Sport=Other and patch the
        Garmin activity type afterward. typeId/parentTypeId are stable
        Garmin enums (walking=9, parent fitness_equipment-or-running=17)."""
        if self._g is None:
            raise RuntimeError("login() must be called first")
        return self._g.set_activity_type(
            str(activity_id),
            type_id=9,
            type_key="walking",
            parent_type_id=17,
        )


    def delete_activity(self, activity_id: int | str) -> Any:
        if self._g is None:
            raise RuntimeError("login() must be called first")
        return self._g.delete_activity(str(activity_id))


def today_utc() -> date:
    return datetime.now(UTC).date()


def backfill_window(days: int) -> tuple[date, date]:
    end = today_utc()
    start = end - timedelta(days=days)
    return start, end
