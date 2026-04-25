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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
