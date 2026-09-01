from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.crawler_identity import RELEASE_CRAWLER_USER_AGENT, validate_crawler_user_agent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BULLETFEED_",
        extra="ignore",
    )

    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    github_webhook_secret: SecretStr = SecretStr("")
    github_callback_url: str = "http://127.0.0.1:8000/v1/auth/github/callback"
    token_encryption_key: SecretStr = SecretStr("")
    database_path: Path = Path("data/bulletfeed.db")
    allowed_origins: str = ""
    rss_allowed_hosts: str = ""
    web_allowed_hosts: str = ""
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 1_048_576
    session_telemetry_enabled: bool = True
    dynamic_web_enabled: bool = False
    dynamic_web_allowed_hosts: str = ""
    dynamic_web_timeout_seconds: float = 8.0
    dynamic_web_max_output_bytes: int = 1_048_576
    dynamic_web_max_subresources: int = 8
    dynamic_web_max_memory_mb: int = 128
    crawler_user_agent: str = RELEASE_CRAWLER_USER_AGENT
    embed_source_sync_worker: bool = True

    @field_validator("crawler_user_agent")
    @classmethod
    def _crawler_user_agent(cls, value: str) -> str:
        return validate_crawler_user_agent(value)

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def rss_hosts(self) -> set[str]:
        return {
            item.strip().lower().rstrip(".") for item in self.rss_allowed_hosts.split(",") if item.strip()
        }

    @property
    def web_hosts(self) -> set[str]:
        return {
            item.strip().lower().rstrip(".") for item in self.web_allowed_hosts.split(",") if item.strip()
        }

    @property
    def dynamic_web_hosts(self) -> set[str]:
        return {
            item.strip().lower().rstrip(".")
            for item in self.dynamic_web_allowed_hosts.split(",")
            if item.strip()
        }

    @property
    def github_auth_configured(self) -> bool:
        return bool(
            self.github_client_id
            and self.github_client_secret.get_secret_value()
            and self.token_encryption_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
