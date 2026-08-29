from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 1_048_576

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def rss_hosts(self) -> set[str]:
        return {
            item.strip().lower().rstrip(".") for item in self.rss_allowed_hosts.split(",") if item.strip()
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
