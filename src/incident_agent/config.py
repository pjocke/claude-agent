from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    anthropic_api_key: str
    grafana_url: str
    grafana_service_account_token: str
    slack_bot_token: str
    slack_channel_id: str
    pagerduty_api_key: str
    pagerduty_service_id: str
    max_agent_turns: int = 10
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
