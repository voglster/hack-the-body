from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HTB_AGENT_")

    mqtt_host: str = "10.0.6.11"
    mqtt_port: int = 1883
    mqtt_user: str = "kiosk-office"
    mqtt_password: str
    mqtt_keepalive: int = 30

    device_id: str = "jims_office_kiosk"
    device_name: str = "Jim's Office Kiosk"
    topic_prefix: str = "office/jims-kiosk"
    discovery_prefix: str = "homeassistant"

    state_poll_seconds: float = 5.0
    preview_seconds: float = 5.0
    preview_max_width: int = 720
    preview_jpeg_quality: int = 40

    chromium_cdp_port: int = 9222
    display: str = ":0"
    xauthority: str = "/home/jvogel/.Xauthority"
    kiosk_user: str = "jvogel"
