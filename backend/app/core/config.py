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
    admin_session_ttl_hours: int = 12  # platform admins sign in again at least this often
    password_reset_ttl_minutes: int = 30
    invitation_ttl_hours: int = 72
    # Optional "claim your business" invitations for admin-managed businesses. OFF by default: nothing about cards, scans or review pages ever needs an account. When on, an administrator may invite a
    # shopkeeper to take ownership of the business record the administrator created; the invitation expires after CLAIM_INVITATION_TTL_HOURS and can be revoked.
    claim_invitations_enabled: bool = False  # CLAIM_INVITATIONS_ENABLED
    claim_invitation_ttl_hours: int = 168  # CLAIM_INVITATION_TTL_HOURS

    # Website builder (static business websites an administrator builds and publishes). OFF by default: with SITES_ENABLED=false every site route answers "sites_disabled" and nothing else in
    # FlowQR changes. See docs/WEBSITE_BUILDER.md for the architecture and docs/WEBSITE_BUILDER_CLOUDFLARE.md for the hosting prerequisites.
    sites_enabled: bool = False  # SITES_ENABLED
    sites_base_domain: str = "sites.localhost"  # SITES_BASE_DOMAIN: business sites are <slug>.<this>. Production: flowqr.site (see the cookie-scope rule below) or a separate registrable domain
    sites_provider: str = "local"  # SITES_PROVIDER: local (development and tests only) | cloudflare
    sites_local_dir: str = "/tmp/flowqr-sites"  # SITES_LOCAL_DIR: where the local provider writes
    sites_service_token: str = ""  # SITES_SERVICE_TOKEN: shared secret between the hosting Worker and the enquiry endpoint (at least 32 characters)
    sites_accept_shared_cookie_scope: bool = False  # SITES_ACCEPT_SHARED_COOKIE_SCOPE: see check_production
    sites_grace_days: int = 14  # SITES_GRACE_DAYS: how long an expired site stays up before it is suspended (its content is never deleted by a lapse)
    sites_enquiry_retention_days: int = 180  # SITES_ENQUIRY_RETENTION_DAYS: enquiries older than this are deleted
    sites_enquiry_notifier: str = "none"  # SITES_ENQUIRY_NOTIFIER: none | smtp. "smtp" is NOT recommended on the shared Gmail account (quota, deliverability): review first
    cloudflare_account_id: str = ""  # CLOUDFLARE_ACCOUNT_ID
    cloudflare_api_token: str = ""  # CLOUDFLARE_API_TOKEN: scoped to Workers KV edit on ONE namespace (and optionally cache purge on ONE zone). Server-side only
    cloudflare_kv_namespace_id: str = ""  # CLOUDFLARE_KV_NAMESPACE_ID: the host -> site pointer table the Worker reads
    cloudflare_zone_id: str = ""  # CLOUDFLARE_ZONE_ID: optional, for cache purge after a publish
    r2_bucket: str = ""  # R2_BUCKET: the published static files
    r2_access_key_id: str = ""  # R2_ACCESS_KEY_ID: an R2 token limited to that one bucket (object read and write)
    r2_secret_access_key: str = ""  # R2_SECRET_ACCESS_KEY

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
    # API prices (USD per unit), keyed "<provider>.<operation>", e.g. {"places.searchText": 0.032}. EMPTY BY DEFAULT: an unconfigured price is recorded as unpriced, never as free.
    api_prices: dict = {}
    # Cost inputs for the finance view (all optional; a missing one is shown as MISSING and is never treated as zero). INR unless the name says otherwise.
    usd_inr_rate: float | None = None  # needed to put USD API costs next to INR revenue
    hosting_monthly_inr: float | None = None
    payment_fee_pct: float | None = None  # the provider's fee as a % of each captured payment (check the current rate in your Razorpay dashboard)
    card_unit_cost_inr: float | None = None  # PROVISIONAL: about 75 per card (150 for two) was an estimate; packaging, shipping and fulfilment are not confirmed
    card_fulfilment_per_order_inr: float | None = None
    support_monthly_inr: float | None = None
    marketing_spend_monthly_inr: float | None = None  # for CAC
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
    # Balanced Autonomy (services/agent/autonomy_policy.py, executor.py). Autonomy itself is OFF per business until an owner turns it on.
    autonomy_emergency_stop: bool = False  # platform-wide: no autonomous or approved profile write runs, scheduled publishing jobs hold. Also flippable at runtime.
    autonomy_failure_suspend: int = 3  # consecutive failed executions after which a business's autonomy is suspended
    autonomy_max_attempts: int = 4  # attempts per action for transient Google errors
    autonomy_approval_ttl_hours: int = 72  # a person's approval is valid this long
    autonomy_auto_auth_ttl_hours: int = 24  # an automatic (policy / pre-authorised) authorisation is valid this long: stale ones are re-evaluated
    autonomy_proposal_ttl_days: int = 7  # a proposal nobody decides on expires
    autonomy_stuck_minutes: int = 10  # an action "executing" this long was left behind by a crash
    # Data retention (docs/DATA_RETENTION.md). 0 = keep until the business is deleted.
    autonomy_history_retention_days: int = 730  # finished actions, their approvals and their tamper-evident history are erased this long after they were created
    rank_grid_retention_days: int = 400  # geo-grid scans and their points
    ai_review_risk_check: bool = True  # an AI safety read of each review when a reply is drafted, on top of the deterministic rules (services/ai/risk.py)
    public_ai_max_input_chars: int = 1200

    # Review Growth (QR campaigns + AI review drafts)
    # Planned integrations (Releases 2 and 3). Setting these does NOT make anything work: there is no adapter yet, and the UI says so.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    rank_provider: str = ""
    rank_provider_key: str = ""  # Google Places API (New) key when rank_provider == "google_places"; never logged or returned by the API
    rank_max_keywords_per_location: int = 10  # search terms one location may track. PROVISIONAL (owner has not set the per-plan number); raise or lower here
    rank_monthly_check_cap: int = 300  # Places calls one business may spend per calendar month (each keyword check = 1 call): bounds your Google bill
    rank_radius_m: int = 3000  # how far around the location the search is biased (metres)
    rank_auto_check_days: int = 7  # keywords are re-checked automatically this often
    # Geo-grid ranking. Every grid point is ONE billed Places search, so all of this is about bounding the Google bill.
    # Map allowances (maps per location, points per map, searches per month) are NOT set here: they are plan limits (billing_plans.limits.geo), unapproved by the owner, and maps stay off until set.
    rank_grid_min_spacing_m: int = 250  # closer points would be the same search twice
    rank_grid_max_spacing_m: int = 10000
    rank_grid_auto_days: int = 7  # an active grid is re-scanned automatically this often (only when the whole scan fits the monthly allowance)
    rank_platform_monthly_cap: int = 0  # Places searches the whole platform may spend per month across every business (0 = no platform cap)
    # --- geo-grid (maps) master controls. Maps stay OFF until ALL of these are deliberately set, and any of them can switch maps off again (restart api and worker).
    rank_grid_enabled: bool = False  # RANK_GRID_ENABLED: master switch and emergency stop. A plan alone can never turn maps on; false refuses every manual and automatic scan.
    rank_platform_daily_cap: int = 0  # RANK_PLATFORM_DAILY_CAP: Places searches the whole platform may spend per UTC day (0 = unset). Maps refuse to run while BOTH platform caps are 0.
    rank_alert_pct: int = 80  # Admin > Operations warns when platform Places use reaches this percentage of a cap
    rank_cost_per_call_usd: float = 0.0  # your Places price per search, to show estimated spend (0 = unpriced: only call counts are shown)
    places_suggest_enabled: bool = True  # PLACES_SUGGEST_ENABLED: business and address suggestions while setting up (uses the Places key above; no key = forms stay manual)
    places_suggest_user_daily_cap: int = 150  # Google calls (typing counts) one person may spend on suggestions per day
    places_suggest_monthly_cap: int = 3000  # the whole platform's Google calls for suggestions per month (0 = no cap)
    account_deletion_grace_days: int = 14  # how long an owner can cancel a deletion request (a business), or a person can cancel deleting their own account
    user_deletion_confirm_hours: int = 24  # the emailed "confirm deleting my account" link works once, for this long
    reauth_window_minutes: int = 15  # deleting your own account needs a password, or (Google-only accounts) a sign-in this recent
    # Provisional retention, owner-approved 2026-11-18, PENDING LEGAL REVIEW (not a statement of compliance). 0 = keep. The scheduled job is OFF until PRIVACY_RETENTION_ENABLED=true,
    # so nothing is deleted just because this code was deployed; `privacy-retention-report` (CLI) counts what would go without deleting anything.
    privacy_retention_enabled: bool = False
    session_retention_days: int = 30  # ended (expired or signed-out) login sessions, which hold an IP address and a browser string
    password_reset_token_retention_days: int = 30  # password-reset tokens, whether used or not (they stop working after minutes; this removes the rows)
    audit_ip_retention_days: int = 365  # only the IP address is removed from an audit entry; the entry itself stays
    lead_retention_days: int = 365  # demo requests from the marketing site
    # AI safeguard (docs/PRIVACY_COMPLIANCE_AUDIT.md, finding 26e). Review text and customers' typed words are personal data. Gemini's data-use terms for this project's key have NOT been
    # confirmed, so review data is not sent to Gemini unless GEMINI_DATA_TERMS_VERIFIED=true (set only after the owner has the evidence). AI_REVIEW_DATA_KILL_SWITCH=true stops review data
    # going to ANY provider, at once. Neither setting changes AI that works only from the owner's own business facts (posts, ideas).
    ai_review_data_kill_switch: bool = False
    gemini_data_terms_verified: bool = False
    support_email: str = ""  # shown on the legal pages; empty = pages say it is not configured
    legal_company_name: str = "FlowHQ"
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

    # Registration gate (services/registration.py). "" = automatic: `allowlist` when APP_ENV is staging or production, `open` otherwise (development and tests). An explicit value always wins;
    # anything that is not closed|allowlist|open is treated as `closed` (fail closed) and refused by the production guard. REGISTRATION_ALLOWLIST: comma separated extra addresses
    # (the platform-admin addresses and the database list managed by an administrator are always honoured too).
    registration_mode: str = ""
    registration_allowlist: str = ""

    # Billing (Razorpay). Test keys (rzp_test_...) => test mode. Empty => billing shows "configuration pending".
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    trial_days: int = 7
    trial_plan: str = "growth"  # trial grants this plan's limits/features

    # Billing provider. EMPTY (the default) = unchanged behaviour: nothing new is switched on. "cashfree" = Cashfree Subscriptions (recurring UPI AutoPay / card mandates).
    # Razorpay stays in the code for historical records but is never used when this is set. Secrets live in the backend environment only.
    billing_provider: str = ""  # BILLING_PROVIDER: "" | "cashfree"
    cashfree_env: str = "sandbox"  # CASHFREE_ENV: sandbox | production (separate credentials for each; never mixed)
    cashfree_client_id: str = ""
    cashfree_client_secret: str = ""
    cashfree_webhook_secret: str = ""  # CASHFREE_WEBHOOK_SECRET: if empty the client secret is used (Cashfree documents "your secret key"; confirm in the sandbox)
    cashfree_api_version: str = "2026-01-01"
    cashfree_sandbox_ack: bool = False  # CASHFREE_SANDBOX_ACK: required to run sandbox credentials with APP_ENV=production (a deliberate, visible choice)
    cashfree_authorization_paise: int = 100  # the refundable authorisation the customer is shown before checkout (Cashfree's minimum for UPI and cards is Rs 1)
    cashfree_methods: str = "upi,card"  # CASHFREE_METHODS: eNACH is deferred and refused by the guard
    cashfree_plan_max_amount_paise: int = 0  # 0 = the highest active plan price, so a plan change never needs a new mandate
    cashfree_charge_settlement_hours: int = 48  # access continues this long after a first charge is due while the payment settles
    cashfree_retry_max: int = 3  # Cashfree allows at most 3 retries of a failed charge per cycle
    cashfree_webhook_tolerance_seconds: int = 300
    # One-time prepaid plans through Cashfree PAYMENT GATEWAY orders (not Subscriptions: no mandate, no authorisation, no recurring charge). OFF unless PREPAID_CHECKOUT_ENABLED=true AND the
    # Cashfree credentials are present. It does NOT depend on BILLING_PROVIDER: that setting only governs the dormant subscription integration.
    prepaid_checkout_enabled: bool = False  # PREPAID_CHECKOUT_ENABLED
    cashfree_pg_api_version: str = "2025-01-01"  # x-api-version for the Orders API (Subscriptions keep CASHFREE_API_VERSION)
    prepaid_notify_url: str = ""  # PREPAID_NOTIFY_URL: https URL of POST /api/v1/webhooks/cashfree-pg, sent with each order so no dashboard setting is needed. Empty = rely on the return page and the hourly check
    prepaid_order_minutes: int = 30  # how long a payment page stays payable
    trial_requires_mandate: bool = True  # TRIAL_REQUIRES_MANDATE: with Cashfree configured, a NEW business gets its free trial only after Cashfree confirms a payment authorisation

    past_due_grace_days: int = 7
    # Per physical card, INR paise. Deliberately NO default: unset => card ordering is disabled (never a silent placeholder price).
    card_price_paise: int | None = None  # legacy per-card price; the bundles in `card_offers` take precedence when the quantity matches one
    # Physical-card bundles (the confirmed offer). Revenue from these is ONE-TIME, never MRR. Setting this to [] turns the bundles off.
    card_offers: list = [{"code": "one", "quantity": 1, "price_paise": 80000}, {"code": "two", "quantity": 2, "price_paise": 100000}]
    promo_card_plan: str = "growth"  # the plan a card purchase includes for a month
    promo_card_days: int = 30  # OWNER DECISION PENDING: length of 'one month' (30 days assumed)
    promo_max_grants_per_business: int = 1  # OWNER DECISION PENDING: a second card order does not earn a second free month unless this is raised
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

    # Operations: error reporting, AI budget, backup freshness. All optional; the ops dashboard says plainly when one is not set.
    sentry_dsn: str = ""  # Sentry (or any Sentry-compatible) DSN for API, worker and beat. Empty = errors are only logged.
    sentry_environment: str = ""  # defaults to APP_ENV
    sentry_traces_sample_rate: float = 0.0
    ai_monthly_budget_usd: float = 0.0  # platform-wide AI spend alert/cap. 0 = no budget set
    ai_price_in_per_mtok: float = 0.0  # USD per 1M input tokens, used only when the provider reports no cost. 0 = unknown
    ai_price_out_per_mtok: float = 0.0
    # AI cost enforcement (services/ai_usage.py). Every model call is written to ai_call_ledger and checked against these BEFORE it is made, retries
    # included. 0 = no limit of that kind. A USD limit needs the prices above: with a USD limit set and no price known, generation is blocked (fail closed)
    # rather than silently unenforced. Customer-facing review writing and the review-risk check are "essential": they stop only at the platform HARD limit.
    ai_tenant_monthly_budget_usd: float = 0.0  # default monthly budget for one business (a business can have its own: tenants.ai_monthly_budget_usd)
    ai_tenant_monthly_token_budget: int = 0  # input + output tokens per business per month
    ai_platform_hard_limit_usd: float = 0.0  # platform-wide monthly hard stop for ALL generation
    ai_platform_monthly_token_limit: int = 0
    ai_platform_soft_pct: int = 90  # at this % of a platform limit, nonessential generation (drafts, agent, posts) stops; essential continues to 100%
    backup_status_file: str = ""  # JSON written by deploy/backup.sh (mount ./backups read-only into the api container)
    backup_max_age_hours: int = 30

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
    def effective_registration_mode(self) -> str:
        m = (self.registration_mode or "").strip().lower()
        if not m:
            return "allowlist" if self.hardened else "open"
        return m if m in ("closed", "allowlist", "open") else "closed"

    @property
    def registration_allowlist_set(self) -> set[str]:
        from app.services.registration import normalize_email  # local import: the service imports settings

        return {n for n in (normalize_email(e) for e in self.registration_allowlist.split(",")) if n}

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
    def cashfree_enabled(self) -> bool:
        return (self.billing_provider or "").strip().lower() == "cashfree"

    @property
    def cashfree_configured(self) -> bool:
        return bool(self.cashfree_enabled and self.cashfree_client_id and self.cashfree_client_secret)

    @property
    def prepaid_configured(self) -> bool:
        """True only when a one-time prepaid purchase can really be taken: switched on explicitly AND credentials present."""
        return bool(self.prepaid_checkout_enabled and self.cashfree_client_id and self.cashfree_client_secret)

    @property
    def mandate_required(self) -> bool:
        """True only when a payment authorisation can really be taken (Cashfree switched on AND credentials present): otherwise nobody would ever be able to start a trial."""
        return bool(self.trial_requires_mandate and self.cashfree_configured)

    @property
    def cashfree_base_url(self) -> str:
        return "https://api.cashfree.com/pg" if (self.cashfree_env or "").strip().lower() == "production" else "https://sandbox.cashfree.com/pg"

    @property
    def cashfree_webhook_key(self) -> str:
        return self.cashfree_webhook_secret or self.cashfree_client_secret

    @property
    def cashfree_method_list(self) -> list[str]:
        return [m.strip().lower() for m in (self.cashfree_methods or "").split(",") if m.strip()]

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
    if (s.registration_mode or "").strip().lower() not in ("", "closed", "allowlist", "open"):
        p.append(f"REGISTRATION_MODE '{s.registration_mode}' is not one of closed, allowlist, open (it would be treated as closed)")
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
    # The site and the API on different hosts (flowqr.site on Vercel, api.flowqr.site on the VPS): the browser only sends the session cookie if it is scoped to the parent domain, and the API only
    # answers the site's own origin. Getting either wrong shows up as "everyone is logged out" or "the browser blocks every request", so refuse to start instead.
    from urllib.parse import urlparse

    fe = urlparse(s.frontend_url)
    if fe.hostname and s.cors_origin_list and f"{fe.scheme}://{fe.netloc}" not in s.cors_origin_list:
        p.append(f"CORS_ORIGINS must include the site's own origin {fe.scheme}://{fe.netloc} (FRONTEND_URL); the browser would block every request from it")
    api_host = urlparse(s.google_redirect_uri).hostname if s.google_configured else None
    if fe.hostname and api_host and api_host != fe.hostname:
        cd = (s.cookie_domain or "").lstrip(".").lower()
        if not cd:
            p.append(f"COOKIE_DOMAIN is required because the site ({fe.hostname}) and the API ({api_host}) are different hosts: set it to their shared parent domain, e.g. .{'.'.join(fe.hostname.split('.')[-2:])}")
        elif not (fe.hostname.lower() == cd or fe.hostname.lower().endswith("." + cd)) or not (api_host.lower() == cd or api_host.lower().endswith("." + cd)):
            p.append(f"COOKIE_DOMAIN '{s.cookie_domain}' does not cover both the site ({fe.hostname}) and the API ({api_host}); sessions would not be sent")
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
    # Cashfree: both credentials together; sandbox and production never mixed; eNACH deferred; Razorpay is never the provider while this is set
    if (s.billing_provider or "").strip().lower() not in ("", "cashfree"):
        p.append(f"BILLING_PROVIDER '{s.billing_provider}' is not one of: (empty), cashfree")
    if s.prepaid_checkout_enabled and not (s.cashfree_client_id and s.cashfree_client_secret):
        p.append("PREPAID_CHECKOUT_ENABLED needs CASHFREE_CLIENT_ID and CASHFREE_CLIENT_SECRET")
    if s.cashfree_enabled or s.cashfree_client_id or s.cashfree_client_secret:
        if not (s.cashfree_client_id and s.cashfree_client_secret):
            p.append("CASHFREE_CLIENT_ID and CASHFREE_CLIENT_SECRET must both be set")
        if (s.cashfree_env or "").strip().lower() not in ("sandbox", "production"):
            p.append(f"CASHFREE_ENV '{s.cashfree_env}' is not one of sandbox, production")
        if (s.cashfree_env or "").strip().lower() == "sandbox" and s.is_production and not s.cashfree_sandbox_ack:
            p.append("CASHFREE_ENV=sandbox with APP_ENV=production needs CASHFREE_SANDBOX_ACK=true (sandbox credentials must never be live by accident)")
        if (s.cashfree_env or "").strip().lower() == "production" and not s.is_production:
            p.append("CASHFREE_ENV=production is only allowed with APP_ENV=production")
        if set(s.cashfree_method_list) - {"upi", "card"}:
            p.append("CASHFREE_METHODS may only contain upi and card (eNACH is not enabled yet)")
        if s.cashfree_enabled and s.razorpay_configured:
            p.append("Razorpay keys must be removed while BILLING_PROVIDER=cashfree (one payment provider only)")
        if s.cashfree_authorization_paise < 100:
            p.append("CASHFREE_AUTHORIZATION_PAISE cannot be below 100 (Cashfree's minimum authorisation for UPI and cards is Rs 1)")
    if s.sites_enabled:
        base = (s.sites_base_domain or "").strip().lower().lstrip(".")
        if not base or "." not in base or base.endswith(".localhost"):
            p.append("SITES_BASE_DOMAIN must be a real domain when SITES_ENABLED is true")
        if s.sites_provider != "cloudflare":
            p.append("SITES_PROVIDER must be cloudflare in production (the local provider is for development and tests)")
        else:
            for name, v in (("CLOUDFLARE_ACCOUNT_ID", s.cloudflare_account_id), ("CLOUDFLARE_API_TOKEN", s.cloudflare_api_token), ("CLOUDFLARE_KV_NAMESPACE_ID", s.cloudflare_kv_namespace_id),
                            ("R2_BUCKET", s.r2_bucket), ("R2_ACCESS_KEY_ID", s.r2_access_key_id), ("R2_SECRET_ACCESS_KEY", s.r2_secret_access_key)):
                if not v:
                    p.append(f"{name} is required when SITES_ENABLED is true and SITES_PROVIDER is cloudflare")
        if len(s.sites_service_token or "") < 32:
            p.append("SITES_SERVICE_TOKEN must be a random value of at least 32 characters when SITES_ENABLED is true")
        cd = (s.cookie_domain or "").lstrip(".").lower()
        if cd and base and (base == cd or base.endswith("." + cd)) and not s.sites_accept_shared_cookie_scope:
            p.append(f"SITES_BASE_DOMAIN '{base}' is inside COOKIE_DOMAIN '{s.cookie_domain}': the session and CSRF cookies are sent to every business website. Use a separate registrable domain, or set "
                     "SITES_ACCEPT_SHARED_COOKIE_SCOPE=true only after reading docs/WEBSITE_BUILDER.md (section Cookie and origin isolation): the sites ship no JavaScript and the Worker never reads or sets cookies")
    return p


def assert_production_safe(s: Settings) -> None:
    """Refuse to boot a staging/production server with unsafe/default configuration."""
    problems = config_problems(s)
    if problems:
        raise RuntimeError("Unsafe " + s.app_env + " configuration:\n  - " + "\n  - ".join(problems))
