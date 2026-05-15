from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_session_dir: str = "./.garminsession"
    garmin_backfill_days: int = 90
    garmin_schedule_cron: str = "0 4 * * *"
    # Intra-day light steps sync (today's daily summary only). Default
    # runs every 30 min from 06:00-22:00 local. Set tz via TZ env var.
    garmin_steps_schedule_cron: str = "*/30 6-22 * * *"
    garmin_steps_schedule_tz: str = "America/Denver"


def get_settings() -> Settings:
    return Settings()
