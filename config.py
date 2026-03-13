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

    # SMTP email (optional — for sending payment links to customers)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # e.g. no-reply@veteranlawnsandlandscapes.com

    # Mobile Text Alerts (optional — SMS notifications)
    mta_api_key: str = ""
    mta_account_id: str = ""

    # Zillow API (optional — property data & valuation)
    zillow_api_key: str = ""
    zillow_api_host: str = "zillow-com.p.rapidapi.com"

    # E-Verify (optional — employment eligibility verification)
    everify_client_id: str = ""
    everify_client_secret: str = ""
    everify_company_id: str = ""
    everify_api_url: str = "https://verify.uscis.gov/api/v1"

    # Paychex (optional — payroll & HR)
    paychex_client_id: str = ""
    paychex_client_secret: str = ""
    paychex_company_id: str = ""
    paychex_api_url: str = "https://api.paychex.com"

    # OpenAI (optional — AI-based grass area estimation)
    openai_api_key: str = ""

    # Mapbox (optional — route maps in weekly schedule)
    mapbox_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
