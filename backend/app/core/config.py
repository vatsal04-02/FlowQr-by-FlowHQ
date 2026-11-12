"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Set by docker-compose.prod.yml: the process must then run hardened, so a forgotten APP_ENV can never skip the guard.
    require_hardened: bool = False
    app_env: str = "development"  # development | test | staging | production  (staging/production are "hardened")
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

    # "Continue with Google" sign-in. A SEPARATE OAuth client from the Business Profile one above: it only ever
    # requests openid/email/profile (no Google verification review) and shares no credentials, scopes or tokens.
    google_login_client_id: str = ""
    google_login_client_secret: str = ""
    google_login_redirect_uri: str = "http://localhost:3000/api/v1/auth/google/callback"

    # AI
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"  # gemini-2.5-flash is closed to new API keys
    gemini_thinking_level: str = "minimal"  # "" to omit (models that do not support thinking levels reject the field)
    # OpenRouter (AI_PROVIDER=openrouter). The key is server-side only. Pick the model by its OpenRouter id.
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    # Any OpenAI-compatible endpoint (AI_PROVIDER=openai_compat), e.g. Groq https://api.groq.com/openai/v1, Mistral https://api.mistral.ai/v1. Server-side key only.
    # Free tiers are fine for development and tests; use a paid plan for real customers (limits and data terms change).
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    openai_compat_model: str = ""
    openai_compat_name: str = "openai_compat"  # label shown in logs and the dashboard
    # Optional PEM file of EXTRA trusted roots for the AI client (a proxy/antivirus that re-signs HTTPS). Adds to, never replaces, normal verification.
    ai_extra_ca_bundle: str = ""
    openrouter_disable_reasoning: bool = True  # skip hidden chain-of-thought: faster, cheaper, and no null replies from reasoning models
    ai_timeout_seconds: int = 25
    public_ai_max_input_chars: int = 1200

    # Review Growth (QR campaigns + AI review drafts)
    review_session_retention_days: int = 90  # customer answers/drafts are deleted after this; aggregate analytics are kept
    review_max_drafts_per_session: int = 5  # 1 generation + 4 regenerations
    review_max_refinements: int = 15  # times a customer can change stars/topics and have the draft rewritten in one session (the page does this automatically)
    # Direct submission to Google from inside FlowQR. NOT AVAILABLE: needs Google partner/API approval that is not publicly obtainable (docs/GOOGLE_DIRECT_REVIEWS.md).
    # Even "approved" does nothing until a real, verified implementation is registered in services/review_submit/google_direct.py.
    google_direct_submission: str = "off"
    review_max_attempts: int = 3  # write -> check -> (told what was wrong) rewrite. Cheap, and only costs latency when a draft fails its checks
    review_verify_with_ai: bool = True  # second AI pass that fact-checks each draft against the customer's answers (fails closed)
    rl_review_generate_per_10min: int = 20  # per visitor IP per campaign. Generous on purpose: a waiting-room Wi-Fi puts many customers behind ONE IP

    # Rate limits (requests per window)
    rate_limit_enabled: bool = True
    rl_auth_per_minute: int = 10
    rl_public_scan_per_minute: int = 60
    rl_public_ai_per_10min: int = 6

    # Bootstrap: comma separated emails that become platform admins on registration.
    platform_admin_emails: str = ""

    # Billing (Razorpay). Test keys (rzp_test_...) => test mode. Empty => billing shows "configuration pending".
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    trial_days: int = 14
    trial_plan: str = "growth"  # trial grants this plan's limits/features
    past_due_grace_days: int = 7
    # Per physical card, INR paise. Deliberately NO default: unset => card ordering is disabled (never a silent placeholder price).
    card_price_paise: int | None = None
    card_order_min_qty: int = 10
    card_order_max_qty: int = 1000
    email_verification_ttl_hours: int = 72
    require_verified_email: bool = True

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
    def hardened(self) -> bool:
        """staging and production share every safety rule (no dev email logging, docs off, strict config guard)."""
        return self.app_env in ("staging", "production")

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
    def google_login_configured(self) -> bool:
        return bool(self.google_login_client_id and self.google_login_client_secret)

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def razorpay_mode(self) -> str | None:
        if not self.razorpay_configured:
            return None
        return "test" if self.razorpay_key_id.startswith("rzp_test_") else "live"

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "openrouter":
            return bool(self.openrouter_api_key and self.openrouter_model)
        if self.ai_provider == "openai_compat":
            return bool(self.openai_compat_base_url and self.openai_compat_api_key and self.openai_compat_model)
        return self.ai_provider == "gemini" and bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


_LOCAL_SUFFIXES = (".localhost", ".local", ".test", ".example", ".invalid", ".internal", ".lan")
_DEV_SECRET_MARKERS = ("flowqr_app_dev", "flowqr_dev", "change-me", "password", "changeme")
_SINK_SMTP_HOSTS = {"localhost", "127.0.0.1", "mailpit", "mailhog", "maildev", "smtp4dev"}


def _bad_host(url: str) -> str | None:
    """Return a reason if `url` is not a real public https URL."""
    import ipaddress
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https":
        return "must be https://"
    if not host or host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        return f"host '{host}' is not a public domain"
    try:
        ipaddress.ip_address(host)
        return "must be a domain name, not an IP address"
    except ValueError:
        return None


def config_problems(s: Settings) -> list[str]:
    """Everything that must be true before a staging/production server may start. Returns human-readable problems."""
    if s.require_hardened and not s.hardened:
        return [f"APP_ENV is '{s.app_env}' but this deployment (docker-compose.prod.yml) requires APP_ENV=staging or APP_ENV=production"]
    if not s.hardened:
        return []
    p: list[str] = []
    if s.secret_key.startswith("change-me") or len(s.secret_key) < 32:
        p.append("SECRET_KEY must be a random value of at least 32 characters")
    if not s.token_encryption_key:
        p.append("TOKEN_ENCRYPTION_KEY is required")
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(s.token_encryption_key.encode())
        except Exception:
            p.append("TOKEN_ENCRYPTION_KEY is not a valid Fernet key")
        if s.token_encryption_key == s.secret_key:
            p.append("TOKEN_ENCRYPTION_KEY must differ from SECRET_KEY")
    if not s.cookie_secure:
        p.append("COOKIE_SECURE must be true")
    if not s.require_verified_email:
        p.append("REQUIRE_VERIFIED_EMAIL must be true")
    for name, url in (("PUBLIC_CARD_BASE_URL (printed on physical cards)", s.public_card_base_url), ("FRONTEND_URL", s.frontend_url)):
        why = _bad_host(url)
        if why:
            p.append(f"{name} {why}")
    if s.google_configured:
        why = _bad_host(s.google_redirect_uri)
        if why:
            p.append(f"GOOGLE_REDIRECT_URI {why}")
    if s.google_login_client_id or s.google_login_client_secret:
        if not s.google_login_configured:
            p.append("GOOGLE_LOGIN_CLIENT_ID and GOOGLE_LOGIN_CLIENT_SECRET must both be set")
        why = _bad_host(s.google_login_redirect_uri)
        if why:
            p.append(f"GOOGLE_LOGIN_REDIRECT_URI {why}")
        if s.google_login_client_id and s.google_login_client_id == s.google_client_id:
            p.append("GOOGLE_LOGIN_CLIENT_ID must be a separate OAuth client from GOOGLE_CLIENT_ID (Business Profile)")
    for o in s.cors_origin_list:
        why = _bad_host(o)
        if why:
            p.append(f"CORS_ORIGINS entry '{o}' {why}")
    if any(m in s.database_url for m in _DEV_SECRET_MARKERS):
        p.append("DATABASE_URL still contains a development password")
    if not s.platform_admin_email_set:
        p.append("PLATFORM_ADMIN_EMAILS must list at least one FlowHQ admin")
    # Email must really leave the building (no dev log sink, no local mail catcher in production)
    if not s.smtp_host:
        p.append("SMTP_HOST is required (invitations and password resets must be deliverable)")
    elif s.is_production and s.smtp_host.lower() in _SINK_SMTP_HOSTS:
        p.append(f"SMTP_HOST '{s.smtp_host}' is a local mail sink, not a real provider")
    # Razorpay: key pair + webhook secret together; test keys never in production, live keys never in staging
    if s.razorpay_key_id or s.razorpay_key_secret:
        if not (s.razorpay_key_id and s.razorpay_key_secret):
            p.append("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must both be set")
        if not s.razorpay_webhook_secret:
            p.append("RAZORPAY_WEBHOOK_SECRET is required when Razorpay keys are set (webhooks are the source of truth)")
        if s.is_production and s.razorpay_key_id.startswith("rzp_test_"):
            p.append("Razorpay TEST keys (rzp_test_) cannot be used in production")
        if s.app_env == "staging" and s.razorpay_key_id.startswith("rzp_live_"):
            p.append("Razorpay LIVE keys (rzp_live_) cannot be used in staging; use rzp_test_ keys")
        if not s.razorpay_key_id.startswith(("rzp_test_", "rzp_live_")):
            p.append("RAZORPAY_KEY_ID does not look like a Razorpay key")
    elif s.razorpay_webhook_secret:
        p.append("RAZORPAY_WEBHOOK_SECRET is set without Razorpay keys")
    if s.card_price_paise is not None and s.card_price_paise <= 0:
        p.append("CARD_PRICE_PAISE must be a positive number of paise (or unset to disable card ordering)")
    return p


def assert_production_safe(s: Settings) -> None:
    """Refuse to boot a staging/production server with unsafe/default configuration."""
    problems = config_problems(s)
    if problems:
        raise RuntimeError("Unsafe " + s.app_env + " configuration:\n  - " + "\n  - ".join(problems))
