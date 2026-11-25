import os
import subprocess
import sys
import uuid

import pytest

# Point the app at the test database BEFORE importing app modules.
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://flowqr_app:flowqr_app_dev@localhost:5432/flowqr_test")
os.environ["MIGRATION_DATABASE_URL"] = os.environ.get(
    "TEST_MIGRATION_DATABASE_URL", "postgresql+psycopg://flowqr:flowqr_dev@localhost:5432/flowqr_test")
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # unreachable on purpose: tests use the in-memory limiter and inline sync
os.environ["TOKEN_ENCRYPTION_KEY"] = "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU="  # TEST ONLY
os.environ["PUBLIC_CARD_BASE_URL"] = "https://go.test.flowqr.example"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:3000/api/v1/google/callback"
os.environ["GEMINI_API_KEY"] = ""
os.environ["REVIEW_MAX_ATTEMPTS"] = "2"  # suite default (call counts in many tests assume write + one retry); production default is 3
os.environ["AI_REVIEW_RISK_CHECK"] = "false"  # tests use scripted stub models whose call order the risk check would disturb; it has its own dedicated tests
os.environ["REVIEW_VERIFY_WITH_AI"] = "false"  # tests use scripted stub models; the fact-check pass has its own dedicated tests
os.environ["CARD_PRICE_PAISE"] = "24900"  # TEST ONLY price
os.environ["PLATFORM_ADMIN_EMAILS"] = "root@flowhq-admin.example.com"
os.environ["REVIEW_HINGLISH_CHANCE"] = "0"  # production sometimes writes a Hinglish suggestion; the older suite scripts English drafts, tests/test_review_suggestions.py switches it on
os.environ["REVIEW_SUGGESTIONS_PER_ROUND"] = "1"  # production shows 2-3 suggestions per round; the older suite scripts ONE draft per call, tests/test_review_suggestions.py sets 3
os.environ["REVIEW_MAX_AI_WRITES_PER_SESSION"] = "50"  # production allows 2 AI-written versions per customer visit; older tests drive many, tests/test_review_cap.py sets it back to 2

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.core.config import settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Rebuild the test schema from migrations (also proves migrations work)."""
    owner = create_engine(settings.migration_database_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    env = {**os.environ}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env,
                   cwd=os.path.dirname(os.path.dirname(__file__)))
    yield


@pytest.fixture(autouse=True)
def _reset_limits():
    from app.services.ai import health

    rate_limit.reset_memory_limits()
    health.reset()
    yield


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app, base_url="http://testserver") as c:
        yield c


class Session:
    """A logged-in API user with automatic CSRF header handling."""

    def __init__(self, client_factory, email, password="Str0ngPassw0rd!"):
        from app.main import app

        self.http = TestClient(app, base_url="http://testserver")
        self.email = email
        self.password = password
        self.csrf = None
        self.tenant_id = None

    def _h(self, extra=None):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        h.update(extra or {})
        return h

    def request(self, method, url, **kw):
        headers = self._h(kw.pop("headers", None))
        return self.http.request(method, "/api/v1" + url, headers=headers, **kw)

    def get(self, url, **kw): return self.request("GET", url, **kw)
    def post(self, url, **kw): return self.request("POST", url, **kw)
    def patch(self, url, **kw): return self.request("PATCH", url, **kw)
    def put(self, url, **kw): return self.request("PUT", url, **kw)
    def delete(self, url, **kw): return self.request("DELETE", url, **kw)


def latest_token(to: str, marker: str) -> str:
    """Pull the token out of the most recent test-outbox email sent to `to` containing `marker`."""
    from app.services.mailer import OUTBOX

    for m in reversed(OUTBOX):
        if m["to"] == to and marker in m["body"]:
            return m["body"].split("token=")[1].split()[0].strip()
    raise AssertionError(f"no email to {to} with {marker}")


def make_user(email=None, name="Test User", register=True, verify=True) -> Session:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    s = Session(None, email)
    if register:
        r = s.http.post("/api/v1/auth/register", json={"email": email, "password": s.password, "age_confirmed": True, "full_name": name})
        assert r.status_code == 201, r.text
        s.csrf = r.json()["csrf_token"]
        if verify:
            r = s.http.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")})
            assert r.status_code == 204, r.text
    return s


def make_business(name="Acme Physio", email=None, with_location=True, location_cap: int | None = 10) -> Session:
    """A registered business on the default trial. Growth (the trial plan) includes ONE location, which many older tests (staff scoping, cross-location isolation, cards)
    outgrow, so by default this raises ONLY the location cap of the test business to 10. Features, allowances and everything else stay as the plan defines them.
    Pass location_cap=None to get the plan's real cap (tests/test_phase2_plans.py does)."""
    s = make_user(email)
    r = s.post("/tenants", json={"name": name, "category": "Physiotherapy clinic", "language": "en"})
    assert r.status_code == 201, r.text
    s.tenant_id = r.json()["id"]
    if location_cap is not None:
        owner_exec("UPDATE subscriptions SET max_locations = :n WHERE tenant_id = :t", n=location_cap, t=s.tenant_id)
    if with_location:
        r = s.post("/locations", json={"name": f"{name} - Main", "city": "Lucknow",
                                       "review_url": "https://g.page/r/ABC123/review"})
        assert r.status_code == 201, r.text
        s.location_id = r.json()["id"]
    return s


@pytest.fixture()
def biz_a():
    return make_business("Alpha Physio")


@pytest.fixture()
def biz_b():
    return make_business("Beta Dental")


@pytest.fixture()
def admin():
    """Platform admin (email is in PLATFORM_ADMIN_EMAILS for tests)."""
    email = "root@flowhq-admin.example.com"
    s = Session(None, email)
    r = s.http.post("/api/v1/auth/register", json={"email": email, "password": s.password, "age_confirmed": True, "full_name": "Root"})
    if r.status_code == 409:
        r = s.http.post("/api/v1/auth/login", json={"email": email, "password": s.password})
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 201, r.text
        # Administrator rights are granted only once the address is verified (a stranger must not become admin by typing the address into sign-up).
        assert s.http.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")}).status_code == 204
        r = s.http.post("/api/v1/auth/login", json={"email": email, "password": s.password})
        assert r.status_code == 200, r.text
    s.csrf = r.json()["csrf_token"]
    return s


def owner_query(sql: str, **params):
    """Inspect raw DB state as the table owner with RLS explicitly bypassed (test-only helper)."""
    eng = create_engine(settings.migration_database_url)
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        return c.execute(text(sql), params).all()


def owner_exec(sql: str, **params) -> None:
    """Run a write as the table owner with RLS bypassed (test-only; the app role cannot UPDATE append-only tables)."""
    eng = create_engine(settings.migration_database_url)
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        c.execute(text(sql), params)


def head_revision() -> str:
    """The migration head as the scripts define it (tests that check 'the database is at head' use this, so a new migration does not break them)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()
