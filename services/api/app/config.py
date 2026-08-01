from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"
    api_key: str = "dev-key"
    cors_origins: str = "http://localhost:5173"

    # LiteLLM proxy (OpenAI-compatible). Replaces the direct-to-Ollama LAN
    # calls: reachable from anywhere, and the proxy's model aliases pin the
    # sampling params. The `-fast` aliases have thinking disabled server-side
    # — Ollama 0.32 turned thinking ON by default, which blew past
    # coach_timeout_s and left abandoned generations pinning the GPU.
    llm_base_url: str = "https://llm.jc.gravitate.energy/v1"
    llm_api_key: str = ""
    llm_model: str = "ollama/qwen3.6:27b-q4_K_M-fast"
    coach_timeout_s: float = 30.0

    # Coach scheduler — comma-separated 'HH:MM' local times to fire scheduled
    # insights. Defaults: 7am morning brief, 12pm midday check-in, 5pm pre-evening.
    coach_schedule_local: str = "07:00,12:00,17:00"

    # Weekly review — uses a much bigger local model on the framework box
    # (RTX 4090, 128GB) where gpt-oss:120b can fit. Slow, deep, runs once
    # a week. Sunday at 21:00 by default.
    # DEPRECATED: superseded by the unified nudges push tick (see
    # services/nudges.py PUSH_BUCKETS). Kept here only so existing .env
    # files don't break on import. The value is now ignored.
    vitamin_reminder_local: str = "10:00"

    # Weekly review — same proxy, but the non-`fast` alias so the model is
    # free to think. Slow and deep, runs once a week.
    weekly_llm_model: str = "ollama/qwen3.6:35b-a3b-q8_0"
    weekly_timeout_s: float = 600.0
    coach_weekly_local: str = "21:00"  # Sunday HH:MM

    # USDA FoodData Central — fallback barcode/food lookup for items not in
    # Open Food Facts (which is EU-leaning). Free key from api.data.gov.
    usda_fdc_api_key: str = ""

    # Hevy webhook bearer secret. If unset, /webhooks/hevy returns 503.
    hevy_webhook_secret: str | None = None

    # Web Push (VAPID). The 'subject' is a contact mailto: per RFC 8292.
    # Keys are optional — if either is empty, the app generates a fresh
    # keypair on first start and persists it in the user_profile collection.
    vapid_subject: str = "mailto:hack-the-body@local"
    vapid_public_key: str = ""
    vapid_private_key: str = ""

    @property
    def vitamin_reminder_time(self) -> tuple[int, int] | None:
        s = self.vitamin_reminder_local.strip()
        if not s:
            return None
        hh, mm = s.split(":")
        return int(hh), int(mm)

    @property
    def coach_weekly_time(self) -> tuple[int, int]:
        hh, mm = self.coach_weekly_local.strip().split(":")
        return int(hh), int(mm)

    @property
    def coach_schedule_times(self) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for raw in self.coach_schedule_local.split(","):
            stripped = raw.strip()
            if not stripped:
                continue
            hh, mm = stripped.split(":")
            out.append((int(hh), int(mm)))
        return out

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
