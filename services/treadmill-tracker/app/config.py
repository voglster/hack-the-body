from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"

    bridge_host: str = "treadmill-bridge.local"
    bridge_port: int = 8023

    # Active mode: full sweep at this rate (Hz)
    active_poll_hz: float = 2.0
    # Idle mode: probe interval (seconds)
    idle_probe_interval_s: float = 15.0
    # Per-command read timeout in active mode
    active_read_timeout_s: float = 0.6
    # Per-command read timeout in idle mode
    idle_read_timeout_s: float = 0.2
    # Active -> idle: this many consecutive sweep failures
    active_fail_threshold: int = 3


def get_settings() -> Settings:
    return Settings()
