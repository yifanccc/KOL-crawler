from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "kol-signal-api"
    environment: str = "development"
    database_url: str = Field(
        default="sqlite:///./kol_signal.db",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    encryption_key: str = Field(default="dev-encryption-key-change-me", alias="ENCRYPTION_KEY")
    admin_username: str | None = Field(default=None, alias="ADMIN_USERNAME")
    admin_password_hash: str | None = Field(default=None, alias="ADMIN_PASSWORD_HASH")
    jwt_secret: str | None = Field(default=None, alias="JWT_SECRET")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    auth_cookie_name: str = Field(default="kol_session", alias="AUTH_COOKIE_NAME")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    web_origin: str = Field(default="http://localhost:3000", alias="WEB_ORIGIN")
    collector_agent_id: str | None = Field(default=None, alias="COLLECTOR_AGENT_ID")
    collector_token_hash: str | None = Field(default=None, alias="COLLECTOR_TOKEN_HASH")
    collector_poll_seconds: int = Field(default=60, ge=1, alias="COLLECTOR_POLL_SECONDS")
    analysis_poll_seconds: int = Field(default=10, ge=1, alias="ANALYSIS_POLL_SECONDS")
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    model_api_style: Literal["responses", "chat_completions"] = Field(
        default="chat_completions",
        alias="MODEL_API_STYLE",
    )
    openai_base_url: str = Field(default="https://api.deepseek.com", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-v4-pro", alias="OPENAI_MODEL")
    model_reasoning_effort: str = Field(default="high", alias="MODEL_REASONING_EFFORT")
    model_timeout_seconds: int = Field(default=180, ge=30, alias="MODEL_TIMEOUT_SECONDS")
    x_bearer_token: str | None = Field(default=None, alias="X_BEARER_TOKEN")
    x_target_handle: str = Field(default="aleabitoreddit", alias="X_TARGET_HANDLE")
    backfill_limit: int = Field(default=10, alias="BACKFILL_LIMIT")
    enable_scheduler: bool = Field(default=True, alias="ENABLE_SCHEDULER")
    scheduler_poll_seconds: int = Field(default=60, alias="SCHEDULER_POLL_SECONDS")
    lock_ttl_seconds: int = Field(default=300, alias="LOCK_TTL_SECONDS")
    startup_backfill_enabled: bool = Field(default=False, alias="STARTUP_BACKFILL_ENABLED")
    ntfy_server: str | None = Field(default=None, alias="NTFY_SERVER")
    ntfy_topic: str | None = Field(default=None, alias="NTFY_TOPIC")
    ntfy_token: str | None = Field(default=None, alias="NTFY_TOKEN")
    bootstrap_file: Path = Field(
        default=Path("/app/data/bootstrap_posts.json"),
        alias="BOOTSTRAP_FILE",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def model_api_key(self) -> str | None:
        hostname = urlparse(self.openai_base_url).hostname or ""
        if hostname == "api.deepseek.com" or hostname.endswith(".api.deepseek.com"):
            return self.deepseek_api_key
        return self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configured_web_origins(settings: Settings) -> list[str]:
    origins = [origin.strip() for origin in settings.web_origin.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("WEB_ORIGIN must contain at least one origin")
    if "*" in origins:
        raise RuntimeError("WEB_ORIGIN cannot use a wildcard when credentials are enabled")
    return origins


def validate_runtime_settings(settings: Settings) -> None:
    missing = []
    if not settings.admin_username:
        missing.append("ADMIN_USERNAME")
    if not settings.admin_password_hash:
        missing.append("ADMIN_PASSWORD_HASH")
    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        missing.append("JWT_SECRET (at least 32 characters)")
    if not getattr(settings, "collector_agent_id", None):
        missing.append("COLLECTOR_AGENT_ID")
    if not getattr(settings, "collector_token_hash", None) or len(settings.collector_token_hash) != 64:
        missing.append("COLLECTOR_TOKEN_HASH (SHA-256 hex)")
    if missing:
        raise RuntimeError("Missing required security configuration: " + ", ".join(missing))
    configured_web_origins(settings)
