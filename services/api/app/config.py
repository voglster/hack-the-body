from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"
    api_key: str = "dev-key"
    cors_origins: str = "http://localhost:5173"

    # Local Ollama for the coach. Default points at jv-desktop2 on the LAN.
    ollama_url: str = "http://10.0.6.46:11434"
    ollama_model: str = "glm-4.7-flash:latest"
    coach_timeout_s: float = 30.0

    # Coach scheduler — comma-separated 'HH:MM' local times to fire scheduled
    # insights. Defaults: 7am morning brief, 12pm midday check-in, 5pm pre-evening.
    coach_schedule_local: str = "07:00,12:00,17:00"

    # Web Push (VAPID). The 'subject' is a contact mailto: per RFC 8292.
    # Keys are optional — if either is empty, the app generates a fresh
    # keypair on first start and persists it in the user_profile collection.
    vapid_subject: str = "mailto:hack-the-body@local"
    vapid_public_key: str = ""
    vapid_private_key: str = ""

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
