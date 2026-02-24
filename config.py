"""Application configuration via environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Application
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    debug: bool = False

    # Database
    database_url: str

    # Redis (for rate limiting)
    redis_url: str = "redis://localhost:6379"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # FieldRoutes (optional)
    fieldroutes_api_key: str = ""
    fieldroutes_account_id: str = ""
    fieldroutes_api_url: str = "https://api.fieldroutes.com/v1"

    # Pricing
    price_per_acre: float = 430.0

    # Service scheduling
    service_lead_days: int = 3  # Minimum days before service can start

    # Labor rates for ROM calculations
    labor_rate_standard: float = 45.0  # $/hour for standard labor
    labor_rate_pm: float = 75.0  # $/hour for PM time


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
