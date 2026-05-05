from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hevy_api_key: str | None = None
    hevy_api_base: str = "https://api.hevyapp.com/v1"

    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "hack_the_body"

    hevy_schedule_cron: str = "0 */6 * * *"
    hevy_backfill_days: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
