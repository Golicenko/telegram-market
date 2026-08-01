from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://autoflow:autoflow@localhost:5432/autoflow"
    bot_token: str = ""
    telegram_webhook_secret: str = ""
    admin_id: int | None = None
    admin_telegram_ids: set[int] = Field(default_factory=set)
    railway_public_domain: str | None = None
    public_base_url: str | None = None
    upload_dir: str | None = None
    min_withdrawal_af_coins: int = 100
    regular_listing_fee_after_first: int = 0
    enable_regular_listing_fees: bool = False
    listing_promotion_cost_af_coins: int = 15
    listing_promotion_hours: int = 24
    debug: bool = False
    dev_telegram_id: int | None = None
    dev_telegram_name: str = "Local User"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:4173", "http://localhost:4173"])

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        """Railway exposes postgres:// URLs; the app uses SQLAlchemy's asyncpg driver."""
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+asyncpg://", 1)
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+asyncpg://", 1)
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
