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


def get_settings() -> Settings:
    return Settings()
