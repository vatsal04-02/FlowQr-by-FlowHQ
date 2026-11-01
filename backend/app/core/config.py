"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"  # development | test | production
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt Google tokens at rest.
    token_encryption_key: str = ""

    # App DB connection (should be a NON-superuser role so Row-Level Security applies).
    database_url: str = "postgresql+psycopg://flowqr_app:flowqr_app_dev@localhost:5432/flowqr"
    # Used by Alembic only (table owner). Falls back to database_url.
    migration_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    frontend_url: str = "http://localhost:3000"
    # Base URL printed into QR codes / NFC tags. NEVER hardcode in code.
    public_card_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    cookie_secure: bool = False
    cookie_domain: str = ""
    session_ttl_hours: int = 24 * 14
    password_reset_ttl_minutes: int = 30
    invitation_ttl_hours: int = 72

    # Google OAuth / Business Profile (customers connect their OWN accounts via this app).
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/v1/google/callback"
    google_scopes: str = "https://www.googleapis.com/auth/business.manage"
    review_sync_interval_minutes: int = 30

    # AI
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ai_timeout_seconds: int = 25
    public_ai_max_input_chars: int = 1200

    # Rate limits (requests per window)
    rate_limit_enabled: bool = True
    rl_auth_per_minute: int = 10
    rl_public_scan_per_minute: int = 60
    rl_public_ai_per_10min: int = 6

    # Bootstrap: comma separated emails that become platform admins on registration.
    platform_admin_emails: str = ""

    default_trial_ai_generations_per_month: int = 500

    # Outbound email (invitations, password reset). Leave smtp_host empty to disable sending.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "FlowQR <no-reply@localhost>"
    smtp_starttls: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def platform_admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()}

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider == "gemini" and bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def assert_production_safe(s: Settings) -> None:
    """Refuse to boot a production server with unsafe/default configuration."""
    if not s.is_production:
        return
    problems = []
    if s.secret_key.startswith("change-me") or len(s.secret_key) < 32:
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    if not s.token_encryption_key:
        problems.append("TOKEN_ENCRYPTION_KEY is required")
    if not s.cookie_secure:
        problems.append("COOKIE_SECURE must be true")
    if "localhost" in s.public_card_base_url:
        problems.append("PUBLIC_CARD_BASE_URL must be your real card domain (it is printed on physical cards)")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
