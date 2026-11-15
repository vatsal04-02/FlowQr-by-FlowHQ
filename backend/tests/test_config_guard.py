"""Boot-time safety guard: staging/production must refuse test credentials, placeholders and local endpoints."""
import pathlib
import re

import pytest
from cryptography.fernet import Fernet

from tests.test_billing import rzp  # noqa: F401  (fixture)

from app.core.config import Settings, assert_production_safe, config_problems


def good(**over):
    base = dict(
        app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True,
        public_card_base_url="https://go.flowqr.co.in", frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in",
        database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr", platform_admin_emails="ops@flowhq.in",
        smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
        card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback",
    )
    base.update(over)
    return Settings(_env_file=None, **base)


def test_fully_configured_production_boots():
    assert config_problems(good()) == []
    assert_production_safe(good())


@pytest.mark.parametrize("over,needle", [
    (dict(secret_key="change-me-x"), "SECRET_KEY"), (dict(token_encryption_key=""), "TOKEN_ENCRYPTION_KEY"),
    (dict(token_encryption_key="not-a-fernet-key"), "valid Fernet"), (dict(cookie_secure=False), "COOKIE_SECURE"),
    (dict(public_card_base_url="http://go.flowqr.co.in"), "https"), (dict(public_card_base_url="https://localhost:3000"), "public domain"),
    (dict(public_card_base_url="https://go.flowqr.localhost"), "public domain"), (dict(public_card_base_url="https://10.0.0.5"), "IP address"),
    (dict(public_card_base_url="https://go.flowqr.test"), "public domain"), (dict(frontend_url="http://localhost:3000"), "FRONTEND_URL"),
    (dict(cors_origins="http://localhost:3000"), "CORS_ORIGINS"), (dict(database_url="postgresql+psycopg://flowqr_app:flowqr_app_dev@db/x"), "development password"),
    (dict(platform_admin_emails=""), "PLATFORM_ADMIN_EMAILS"), (dict(smtp_host=""), "SMTP_HOST"), (dict(smtp_host="mailpit"), "local mail sink"),
    (dict(razorpay_key_id="rzp_test_abcdefghij"), "TEST keys"), (dict(razorpay_webhook_secret=""), "WEBHOOK_SECRET"),
    (dict(razorpay_key_id="", razorpay_key_secret=""), "without Razorpay keys"), (dict(razorpay_key_id="key_abc"), "does not look like"),
    (dict(card_price_paise=0), "CARD_PRICE_PAISE"), (dict(require_verified_email=False), "REQUIRE_VERIFIED_EMAIL"),
])
def test_production_refuses_unsafe(over, needle):
    problems = config_problems(good(**over))
    assert any(needle in p for p in problems), problems
    with pytest.raises(RuntimeError):
        assert_production_safe(good(**over))


def test_staging_allows_test_keys_but_not_live_and_local_sink_smtp():
    ok = good(app_env="staging", razorpay_key_id="rzp_test_abcdefghij", smtp_host="mailpit")
    assert config_problems(ok) == []
    assert any("LIVE" in p for p in config_problems(good(app_env="staging")))
    assert config_problems(good(app_env="staging", card_price_paise=None, razorpay_key_id="rzp_test_x1", )) is not None


def test_card_price_has_no_placeholder_default():
    assert Settings.model_fields["card_price_paise"].default is None  # unset => ordering disabled, never a silent price


def test_development_stays_permissive():
    assert config_problems(Settings(_env_file=None, app_env="development")) == []


def test_application_code_contains_no_mock_integrations():
    """Fakes live in tests/ only. Nothing in app/ may define or import a mock/stub/fake integration."""
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    bad = re.compile(r"class\s+(Fake|Stub|Mock)\w*|unittest\.mock|MagicMock|from tests|import tests", re.I)
    offenders = [str(f.relative_to(root)) for f in root.rglob("*.py") if bad.search(f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_card_order_disabled_without_price(monkeypatch, rzp, biz_a):
    from app.core.config import settings as live
    monkeypatch.setattr(live, "card_price_paise", None)
    monkeypatch.setattr(live, "card_offers", [])  # no bundles configured either: ordering is closed
    shipping = {"name": "Dr A", "phone": "9876543210", "address_line": "1 Main Road", "city": "Lucknow", "state": "UP", "postal_code": "226001"}
    r = biz_a.post("/billing/card-orders", json={"quantity": 20, "shipping": shipping})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "card_pricing_not_configured"
    assert biz_a.get("/billing/subscription").status_code == 200
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/v1/billing/plans").json()["card_ordering_enabled"] is False


def test_prod_overlay_cannot_run_in_development_mode():
    """docker-compose.prod.yml sets REQUIRE_HARDENED: a forgotten/incorrect APP_ENV must not skip the guard."""
    assert any("requires APP_ENV" in p for p in config_problems(Settings(_env_file=None, app_env="development", require_hardened=True)))
    assert any("requires APP_ENV" in p for p in config_problems(Settings(_env_file=None, app_env="test", require_hardened=True)))
    assert config_problems(good(require_hardened=True)) == []


# ---- the site (Vercel) and the API (VPS) on different hosts: flowqr.site and api.flowqr.site
def split(**over):
    base = dict(public_card_base_url="https://flowqr.site", frontend_url="https://flowqr.site", cors_origins="https://flowqr.site,https://www.flowqr.site", cookie_domain=".flowqr.site",
                google_redirect_uri="https://api.flowqr.site/api/v1/google/callback", razorpay_key_id="", razorpay_key_secret="", razorpay_webhook_secret="", google_client_id="id", google_client_secret="sec")
    base.update(over)
    return good(**base)


def test_the_split_host_production_configuration_boots():
    assert config_problems(split()) == []


@pytest.mark.parametrize("over,needle", [
    (dict(cookie_domain=""), "COOKIE_DOMAIN is required"),
    (dict(cookie_domain=".example.com"), "does not cover both"),
    (dict(cookie_domain=".api.flowqr.site"), "does not cover both"),
    (dict(cors_origins="https://www.flowqr.site"), "must include the site's own origin"),
])
def test_split_host_production_refuses_settings_that_would_log_everyone_out_or_block_every_request(over, needle):
    problems = config_problems(split(**over))
    assert any(needle in p for p in problems), problems
