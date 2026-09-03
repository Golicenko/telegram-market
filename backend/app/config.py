import hashlib
import os
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+asyncpg://autoflow:autoflow@localhost:5432/autoflow"


def normalize_database_url(value: str) -> str:
    """Return a SQLAlchemy URL that uses the asyncpg driver."""
    value = value.strip()
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def migration_database_url() -> str:
    """Read only the database setting so unrelated app variables cannot block Alembic."""
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(
            "DATABASE_URL is missing. Add it to the AUTOFLOW application service "
            "as a Railway reference, for example ${{Postgres.DATABASE_URL}}."
        )
    if value.startswith("${{") or "DATABASE_URL}}" in value:
        raise RuntimeError(
            "DATABASE_URL contains an unresolved Railway reference. Check the exact "
            "PostgreSQL service name in ${{<service>.DATABASE_URL}}."
        )
    value = normalize_database_url(value)
    if not value.startswith(("postgresql+asyncpg://", "postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL.")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    bot_token: str = ""
    telegram_webhook_secret: str = ""
    admin_id: int | None = None
    admin_telegram_ids: set[int] = Field(default_factory=set)
    railway_public_domain: str | None = None
    public_base_url: str | None = None
    upload_dir: str | None = None
    min_withdrawal_af_coins: int = 15
    listing_promotion_cost_af_coins: int = 15
    listing_promotion_hours: int = 24
    training_delivery_cooldown_seconds: int = Field(default=300, ge=30, le=86400)
    seller_payout_percent: int = Field(default=70, ge=1, le=100)
    star_topup_min: int = Field(default=10, ge=1)
    star_topup_max: int = Field(default=1000, ge=1)
    upload_max_bytes: int = Field(default=30 * 1024 * 1024, ge=1024)
    # Direct uploads still pass through the cloud Bot API (50 MB). Large videos
    # use the Telegram inbox/file_id flow and never transit Railway.
    training_file_upload_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    training_video_max_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1024, le=2 * 1024 * 1024 * 1024)
    training_photo_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    telegram_init_data_max_age_seconds: int = Field(default=86400, ge=300, le=604800)
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=60)
    db_pool_recycle_seconds: int = Field(default=300, ge=30, le=3600)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    deal_transfer_reminder_seconds: int = Field(default=120, ge=1, le=86400)
    deal_notification_poll_seconds: int = Field(default=5, ge=1, le=60)
    seller_response_timeout_seconds: int = Field(default=86400, ge=1, le=604800)
    debug: bool = False
    dev_telegram_id: int | None = None
    dev_telegram_name: str = "Local User"
    # Production is same-origin. Local cross-origin values belong in .env, not defaults.
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        """Railway exposes postgres:// URLs; the app uses SQLAlchemy's asyncpg driver."""
        if isinstance(value, str):
            return normalize_database_url(value)
        return value

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if isinstance(value, str):
            return {int(item.strip()) for item in value.split(",") if item.strip()}
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def merge_admin_id(self):
        if self.admin_id is not None:
            self.admin_telegram_ids.add(self.admin_id)
        return self

    @property
    def externally_reachable_url(self) -> str | None:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain.strip('/')}"
        return None

    @property
    def effective_telegram_webhook_secret(self) -> str:
        """Use an explicit secret or a stable token-derived secret for Telegram webhooks."""
        if self.telegram_webhook_secret:
            return self.telegram_webhook_secret
        if not self.bot_token:
            return ""
        return hashlib.sha256(f"autoflow-webhook:{self.bot_token}".encode()).hexdigest()


@lru_cache
def get_settings() -> Settings:
    return Settings()
