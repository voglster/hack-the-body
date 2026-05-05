import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class HevyClient:
    """Thin wrapper over Hevy's public API. Auth: `api-key: <key>` header."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.hevyapp.com/v1",
        timeout_s: float = 20.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"api-key": api_key},
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def list_workouts(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        r = self._client.get("/workouts", params={"page": page, "pageSize": page_size})
        r.raise_for_status()
        return r.json()

    def get_workout(self, workout_id: str) -> dict[str, Any]:
        r = self._client.get(f"/workouts/{workout_id}")
        r.raise_for_status()
        body = r.json()
        # Hevy sometimes wraps singular fetches under {"workout": {...}}.
        return body.get("workout", body)

    def fetch_events(
        self, since: str, page: int = 1, page_size: int = 10,
    ) -> dict[str, Any]:
        r = self._client.get(
            "/workouts/events",
            params={"since": since, "page": page, "pageSize": page_size},
        )
        r.raise_for_status()
        return r.json()
