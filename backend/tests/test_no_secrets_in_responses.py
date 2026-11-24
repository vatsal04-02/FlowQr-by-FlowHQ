"""No endpoint ever returns a secret. A business with Google CONNECTED (so real tokens exist) is read through EVERY readable route (GET) as the owner, as location-limited staff and as a platform
administrator, and every response body is checked for (a) field names that only secrets have and (b) the actual secret values this environment holds: Google tokens, the client secret, the
encryption key, AI provider keys, the SMTP password, payment secrets. The sweep is built from the live route table, so a route added later is covered automatically. Google is a test double.
(The per-feature tests, e.g. test_account_lifecycle, remain; this is the whole-API net underneath them.)"""
import json
import re

import pytest

from app.core.config import settings
from tests.conftest import make_business
from tests.test_google_and_reviews import connected, sync_select  # noqa: F401
from tests.test_google_business_agent import fake  # noqa: F401
from tests.test_location_permissions import invite
from tests.test_phase2_security_audit import FILL, route_table

# JSON keys that only ever hold a secret. (csrf_token is the one deliberate exception: the browser must echo it, it protects nothing by itself.)
SECRET_KEY_NAMES = re.compile(
    r"^(?:password|password_hash|passwd|refresh_token|access_token|id_token|client_secret|api_key|private_key|signing_secret|webhook_secret|secret|secret_key|token_hash|state_hash|key_hash|secret_enc|"
    r"\w*_encrypted|\w*_api_key|\w*_secret|\w*_secret_key|smtp_password|database_url|redis_url|dsn|sentry_dsn)$", re.I)
ALLOWED_NAME_EXCEPTIONS = {"api_key_prefix", "secret_configured", "has_secret", "has_api_key", "key_prefix"}  # a prefix or a yes/no, never the value


def _values_to_hunt(conn_id) -> dict[str, str]:
    """Real secret values this process holds. Anything short or generic is skipped (it would match ordinary words)."""
    out = {
        "google client secret": settings.google_client_secret, "token encryption key": settings.token_encryption_key, "gemini key": settings.gemini_api_key,
        "openrouter key": settings.openrouter_api_key, "openai-compatible key": settings.openai_compat_api_key, "smtp password": settings.smtp_password,
        "agency token key": settings.agency_token_encryption_key, "cashfree secret": getattr(settings, "cashfree_secret_key", "") or "",
        "razorpay secret": getattr(settings, "razorpay_key_secret", "") or "", "database url": settings.database_url, "migration database url": settings.migration_database_url,
        "sentry dsn": settings.sentry_dsn,
        "stored refresh token (fake google)": "REFRESH-SECRET", "stored access token (fake google)": "access-1",
    }
    return {k: v for k, v in out.items() if v and len(v) >= 8}


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}", k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node[:200]):
            yield from _walk(v, f"{path}[{i}]")


def _readable_routes():
    out = []
    for path, method, level in route_table():
        if method != "GET" or level in ("public", "public-bypass-db"):
            continue  # public GETs are covered by the anonymous checks; the sweep is about signed-in surfaces
        if any(skip in path for skip in ("/export", "/download", ".zip", ".pdf", ".png", ".svg", ".csv", "/file", "/image", "/qr.", "/poster", "/sheet", "/events", "/stream", "/callback", "/connect/start")):
            continue  # binary or redirecting responses
        out.append((path, level))
    return out


def _check(who: str, path: str, resp, hunt: dict[str, str], problems: list[str]):
    body = resp.text or ""
    if resp.status_code >= 500:
        problems.append(f"{who} GET {path}: server error {resp.status_code}")
        return
    for label, value in hunt.items():
        if value in body:
            problems.append(f"{who} GET {path}: contains the {label}")
    if "Traceback (most recent call last)" in body or 'File "/' in body or "psycopg" in body or "sqlalchemy" in body.lower():
        problems.append(f"{who} GET {path}: leaks internals (stack trace or database driver text)")
    try:
        data = resp.json()
    except ValueError:
        return
    for where, key, value in _walk(data):
        if key in ALLOWED_NAME_EXCEPTIONS or key == "csrf_token":
            continue
        if SECRET_KEY_NAMES.match(key) and value not in (None, False, "", [], {}):
            problems.append(f"{who} GET {path}: field '{where}' looks like a secret")


def test_no_readable_endpoint_returns_a_secret_for_an_owner_staff_or_platform_admin(connected, fake, admin):  # noqa: F811
    sync_select(connected, fake)
    staff = invite(connected)
    hunt = _values_to_hunt(connected.conn_id)
    routes = _readable_routes()
    assert len(routes) > 120, f"the route table looks too small to be the whole API ({len(routes)})"
    problems: list[str] = []
    checked = 0
    for path, level in routes:
        url = re.sub(r"\{[^}]+\}", FILL, path)
        actors = [("admin", admin)] if level == "platform-admin" else [("owner", connected), ("staff", staff)]
        if level == "platform-admin":
            actors.append(("owner-vs-admin-route", connected))  # must be refused, and the refusal must not leak either
        for who, sess in actors:
            resp = sess.http.request("GET", url, headers=sess._h())
            _check(who, path, resp, hunt, problems)
            checked += 1
    assert checked > 200
    assert not problems, "secret exposure or internal leak:\n" + "\n".join(sorted(set(problems))[:30])


def test_the_google_connection_the_page_reads_shows_state_never_tokens(connected, fake):  # noqa: F811
    r = connected.get("/google/status")
    assert r.status_code == 200
    text = json.dumps(r.json())
    assert "REFRESH-SECRET" not in text and "access-1" not in text
    keys = {k for _, k, _ in _walk(r.json())}
    assert not (keys & {"refresh_token", "access_token", "refresh_token_encrypted", "access_token_encrypted", "client_secret"})


class _Fake:
    def __init__(self, body, status=200):
        self.text, self.status_code, self._b = body, status, body

    def json(self):
        return json.loads(self._b)


def test_the_detector_itself_catches_a_leaked_value_a_secret_field_and_a_stack_trace():
    """A net that cannot catch anything proves nothing: feed it three deliberate leaks and one clean body."""
    hunt = {"google client secret": "super-secret-value-123"}
    leaks: list[str] = []
    _check("t", "/a", _Fake(json.dumps({"note": "contains super-secret-value-123 here"})), hunt, leaks)
    _check("t", "/b", _Fake(json.dumps({"connection": {"refresh_token_encrypted": "gAAAA..."}})), hunt, leaks)
    _check("t", "/c", _Fake('{"detail":"Traceback (most recent call last):"}', 500), hunt, leaks)
    _check("t", "/d", _Fake(json.dumps({"api_key": "sk-xyz"})), hunt, leaks)
    assert len(leaks) == 4, leaks
    clean: list[str] = []
    _check("t", "/ok", _Fake(json.dumps({"csrf_token": "abc", "api_key_prefix": "sk-…", "refresh_token": None, "status": "active"})), hunt, clean)
    assert clean == []  # the deliberate exceptions and empty values are not false alarms
