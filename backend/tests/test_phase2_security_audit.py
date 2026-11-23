"""Phase 2 security audit: regression tests for the findings in docs/PHASE_2_SECURITY_AUDIT.md, plus three systematic controls.

Systematic controls (so a NEW route cannot quietly be less protected than its neighbours):
  * route access manifest: every route's access level (public / signed-in / member / admin / owner / platform admin) is pinned in
    tests/route_access_manifest.txt; adding or loosening a route fails this test until a person reviews and re-pins it
  * role sweep: every platform-admin route refuses a business owner, every admin/owner route refuses staff, every owner route refuses an admin
  * database sweep: every tenant table has FORCED row-level security with a policy, the application role cannot bypass it, and append-only ledgers
    really cannot be updated or deleted by the application role
Google, AI and payments are test doubles throughout; these prove FlowQR's own enforcement."""
import os
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core import deps
from app.core.config import settings
from app.main import app
from app.models.base import utcnow
from tests.conftest import Session, latest_token, make_business, make_user, owner_exec, owner_query
from tests.test_location_permissions import invite

MANIFEST = Path(__file__).with_name("route_access_manifest.txt")
FILL = "00000000-0000-0000-0000-000000000001"


# --------------------------------------------------------------------------------------------- route classification

def _flat(routes, prefix=""):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix, r
        elif type(r).__name__ == "_IncludedRouter":  # FastAPI >= 0.16x wraps include_router()
            yield from _flat(r.original_router.routes, prefix + (getattr(r.include_context, "prefix", "") or ""))
        elif hasattr(r, "app") and hasattr(r.app, "routes"):
            yield from _flat(r.app.routes, prefix + getattr(r, "path", ""))


def _level(route: APIRoute) -> str:
    found: set[str] = set()

    def walk(dep):
        call = dep.call
        if call is deps.get_tenant_context:
            found.add("member")
        elif call is deps.get_auth_context:
            found.add("signed-in")
        elif call is deps.require_platform_admin:
            found.add("platform-admin")
        elif getattr(call, "__name__", "") == "require_operator":
            found.add("operator")  # a listed FlowHQ operator of the internal agency path: a person, not a business role (api/v1/agency_ops.py)
        elif call is deps.public_db:
            found.add("public-bypass-db")
        elif "require_role.<locals>.dependency" in (getattr(call, "__qualname__", "") or "") and call.__closure__:
            found.add("role-" + str(getattr(call.__closure__[0].cell_contents, "value", "?")))
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    for lvl in ("platform-admin", "operator", "role-owner", "role-admin", "role-staff", "member", "signed-in", "public-bypass-db"):
        if lvl in found or any(f == lvl for f in found):
            return lvl
    return "public"


def route_table() -> list[tuple[str, str, str]]:
    rows = []
    for prefix, r in _flat(app.routes):
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append((prefix + r.path, m, _level(r)))
    return sorted(rows)


def _render(rows) -> str:
    return "".join(f"{lvl}\t{m}\t{p}\n" for p, m, lvl in rows)


def test_route_access_manifest_has_not_drifted():
    """A route that is new, removed or protected differently must be reviewed by a person: then run
    `UPDATE_ROUTE_MANIFEST=1 pytest tests/test_phase2_security_audit.py -k manifest` and commit the new file with the change that caused it."""
    now = _render(route_table())
    if os.environ.get("UPDATE_ROUTE_MANIFEST") == "1":
        MANIFEST.write_text(now, encoding="utf-8")
    pinned = MANIFEST.read_text(encoding="utf-8")
    if now != pinned:
        a, b = set(pinned.splitlines()), set(now.splitlines())
        pytest.fail("route access changed. NEW/CHANGED: %s | REMOVED/OLD: %s" % (sorted(b - a)[:15], sorted(a - b)[:15]))


def test_every_route_is_classified_and_nothing_mutating_is_public_by_accident():
    """Public mutating routes are an explicit, reviewed list: anything else public that changes data is a mistake."""
    reviewed_public_writes = {
        "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm", "/api/v1/auth/verify-email",
        "/api/v1/account/me/deletion/confirm",  # reviewed: single-use, expiring, hashed link from the person's own mailbox; 10 per 5 minutes per IP; one identical answer for every failure
        "/api/v1/notifications/unsubscribe",  # reviewed: HMAC-signed link from the person's own notification email, 30 per 5 minutes per IP, only switches that person's email choices OFF, safe to repeat
        "/api/v1/billing/razorpay/webhook",
        "/api/v1/webhooks/cashfree",  # reviewed: signature over the raw body, 5-minute window, stored before processing, treated as a hint (tests/test_cashfree_billing.py)
        "/api/v1/integrations/v1/customers", "/api/v1/integrations/v1/visits", "/api/v1/integrations/v1/enquiries", "/api/v1/integrations/v1/bookings",  # reviewed: authenticated by a hashed, scoped, revocable, rate-limited API key (no cookie, so no CSRF); Pro only; every POST idempotent; never creates consent without an explicit agreement and a note of how (tests/test_whatsapp_integrations.py)
        "/api/v1/webhooks/cashfree-pg",  # reviewed: 404 unless prepaid checkout is on; signature over the raw body, 5-minute window, stored before processing, the order looked up by OUR id and the truth re-read from Cashfree (tests/test_prepaid_checkout.py)
    }
    stray = [(m, p) for p, m, lvl in route_table()
             if lvl == "public" and m != "GET" and p not in reviewed_public_writes]
    assert not stray, f"public routes that change data and are not on the reviewed list: {stray}"


# --------------------------------------------------------------------------------------------- role sweep

def _call(sess: Session, method: str, path: str):
    url = re.sub(r"\{[^}]+\}", FILL, path)
    return sess.http.request(method, url, headers=sess._h(), json={} if method != "GET" else None)


def test_a_business_owner_is_refused_by_every_platform_admin_route():
    owner = make_business("Sweep Owner")
    leaks = []
    for p, m, lvl in route_table():
        if lvl == "platform-admin":
            r = _call(owner, m, p)
            if r.status_code != 403:
                leaks.append((m, p, r.status_code))
    assert not leaks, f"platform-admin routes that a business owner could reach: {leaks}"


def test_staff_are_refused_by_every_admin_and_owner_route_and_admins_by_every_owner_route():
    owner = make_business("Sweep Roles")
    staff = invite(owner, role="staff")
    admin_member = invite(owner, role="admin")
    leaks = []
    for p, m, lvl in route_table():
        if lvl in ("role-admin", "role-owner"):
            r = _call(staff, m, p)
            if r.status_code != 403:
                leaks.append(("staff", m, p, r.status_code))
        if lvl == "role-owner":
            r = _call(admin_member, m, p)
            if r.status_code != 403:
                leaks.append(("admin", m, p, r.status_code))
    assert not leaks, f"routes reachable by a lower role than they require: {leaks}"


def test_member_routes_refuse_a_signed_in_user_with_no_business_and_a_user_of_another_business():
    outsider = make_user()  # signed in, member of nothing
    other = make_business("Not Yours")
    leaks = []
    for p, m, lvl in route_table():
        if lvl in ("member", "role-staff", "role-admin", "role-owner"):
            r = _call(outsider, m, p)
            if r.status_code != 403:
                leaks.append(("no-business", m, p, r.status_code))
            # the tenant header is a selector among the caller's OWN businesses only
            r = outsider.http.request(m, re.sub(r"\{[^}]+\}", FILL, p), headers=outsider._h({"X-Tenant-Id": other.tenant_id}), json={} if m != "GET" else None)
            if r.status_code != 403:
                leaks.append(("foreign-tenant-header", m, p, r.status_code))
    assert not leaks, f"business routes that answered someone with no access to the business: {leaks}"


# --------------------------------------------------------------------------------------------- finding: admin takeover by sign-up

def _as_admin_address(monkeypatch, email):
    monkeypatch.setattr(settings, "platform_admin_emails", f"{settings.platform_admin_emails},{email}")


def test_typing_an_admin_address_into_sign_up_does_not_make_a_stranger_an_administrator(monkeypatch):
    email = f"owner-{os.urandom(4).hex()}@example.com"
    _as_admin_address(monkeypatch, email)
    stranger = make_user(email, verify=False)  # registers; has NOT proven they control the mailbox
    me = stranger.get("/auth/me").json()["user"]
    assert me["is_platform_admin"] is False
    assert stranger.get("/admin/stats").status_code == 403
    assert stranger.get("/admin/plans").status_code == 403


def test_administrator_rights_arrive_only_with_a_verified_address_and_a_short_session(monkeypatch):
    email = f"owner-{os.urandom(4).hex()}@example.com"
    _as_admin_address(monkeypatch, email)
    s = make_user(email, verify=False)
    assert s.http.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")}).status_code == 204
    assert s.get("/auth/me").json()["user"]["is_platform_admin"] is True
    assert s.get("/admin/stats").status_code == 200
    rows = owner_query("SELECT expires_at FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE u.email = :e", e=email)
    assert rows and all(r[0] <= utcnow() + timedelta(hours=settings.admin_session_ttl_hours, minutes=1) for r in rows), "sessions opened before the grant were not shortened"
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'auth.platform_admin_granted' AND user_id = (SELECT id FROM users WHERE email = :e)", e=email)[0][0] == 1


def test_an_unverified_account_flagged_as_admin_is_still_refused(monkeypatch):
    monkeypatch.setattr(settings, "require_verified_email", True)
    s = make_user(verify=False)
    owner_exec("UPDATE users SET is_platform_admin = true WHERE email = :e", e=s.email)  # e.g. a flag set by hand or left over from an older release
    assert s.get("/admin/stats").status_code == 403
    assert s.http.post("/api/v1/auth/verify-email", json={"token": latest_token(s.email, "verify-email")}).status_code == 204
    assert s.get("/admin/stats").status_code == 200


def test_administrator_sign_in_lasts_hours_and_everyone_elses_lasts_days(admin):
    rows = owner_query("SELECT s.created_at, s.expires_at FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE u.email = :e AND s.revoked_at IS NULL ORDER BY s.created_at DESC LIMIT 1", e=admin.email)
    created, expires = rows[0]
    assert expires - created <= timedelta(hours=settings.admin_session_ttl_hours, minutes=1)
    user = make_user()
    created, expires = owner_query("SELECT s.created_at, s.expires_at FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE u.email = :e ORDER BY s.created_at DESC LIMIT 1", e=user.email)[0]
    assert expires - created >= timedelta(hours=settings.session_ttl_hours - 1)


# --------------------------------------------------------------------------------------------- session and token handling

def test_expired_and_revoked_sessions_are_refused_and_logout_really_ends_the_session():
    s = make_business("Session Probe")
    assert s.get("/tenant").status_code == 200
    owner_exec("UPDATE auth_sessions SET expires_at = now() - interval '1 minute' WHERE user_id = (SELECT id FROM users WHERE email = :e)", e=s.email)
    assert s.get("/tenant").status_code == 401
    t = make_business("Logout Probe")
    cookies = dict(t.http.cookies)
    assert t.post("/auth/logout").status_code == 204
    replay = TestClient(app, base_url="http://testserver", cookies=cookies)
    assert replay.get("/api/v1/tenant").status_code == 401, "a stolen cookie still worked after logout"


def test_password_change_and_reset_end_other_sessions_and_reset_tokens_work_once():
    s = make_user()
    other = TestClient(app, base_url="http://testserver")
    assert other.post("/api/v1/auth/login", json={"email": s.email, "password": s.password}).status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 200
    assert s.post("/auth/change-password", json={"current_password": s.password, "new_password": "Another-Passw0rd-9"}).status_code == 204
    assert other.get("/api/v1/auth/me").status_code == 401
    assert s.get("/auth/me").status_code == 200  # the session that made the change survives
    # reset: the token is single-use and ends every session
    anon = TestClient(app, base_url="http://testserver")
    assert anon.post("/api/v1/auth/password-reset/request", json={"email": s.email}).status_code == 202
    token = latest_token(s.email, "reset-password")
    assert anon.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Yet-Another-Pass-77"}).status_code == 204
    assert anon.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Third-Passw0rd-Zz1"}).status_code == 400
    assert s.get("/auth/me").status_code == 401


def test_login_does_not_reveal_whether_an_account_exists_and_locks_after_repeated_failures():
    s = make_user()
    anon = TestClient(app, base_url="http://testserver")
    wrong_pw = anon.post("/api/v1/auth/login", json={"email": s.email, "password": "Wrong-Passw0rd-1"})
    no_user = anon.post("/api/v1/auth/login", json={"email": "nobody-here@example.com", "password": "Wrong-Passw0rd-1"})
    assert wrong_pw.status_code == no_user.status_code == 401 and wrong_pw.json() == no_user.json()
    reset_known = anon.post("/api/v1/auth/password-reset/request", json={"email": s.email})
    reset_unknown = anon.post("/api/v1/auth/password-reset/request", json={"email": "nobody-here@example.com"})
    assert reset_known.status_code == reset_unknown.status_code == 202 and reset_known.json() == reset_unknown.json()
    victim = make_user()
    codes = [anon.post("/api/v1/auth/login", json={"email": victim.email, "password": "Wrong-Passw0rd-1"}).status_code for _ in range(12)]
    assert 429 in codes and codes[0] == 401, codes


# --------------------------------------------------------------------------------------------- database controls

def test_every_tenant_table_has_forced_row_level_security_and_a_policy():
    tables = [r[0] for r in owner_query(
        "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema "
        "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE' ORDER BY 1")]
    assert len(tables) >= 30, "expected the tenant-scoped tables to be found"
    unprotected = []
    for t in tables:
        flags = owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)", t=f"public.{t}")[0]
        policies = owner_query("SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t", t=t)[0][0]
        if not (flags[0] and flags[1] and policies >= 1):
            unprotected.append((t, tuple(flags), policies))
    assert not unprotected, f"tenant tables without forced row-level security and a policy: {unprotected}"


def test_the_application_role_cannot_bypass_row_level_security_or_own_tables():
    role = owner_query("SELECT current_user")[0][0]
    app_role = settings.database_url.split("//")[1].split(":")[0]
    r = owner_query("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = :r", r=app_role)[0]
    assert tuple(r) == (False, False, False, False), f"application role {app_role} is over-privileged: {tuple(r)}"
    owned = owner_query("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = :r", r=app_role)[0][0]
    assert owned == 0, "the application role owns tables, so it could disable row-level security on them"
    assert role != app_role


@pytest.mark.parametrize("table", ["audit_logs", "subscription_events", "api_usage_ledger", "ai_call_ledger"])
def test_append_only_ledgers_cannot_be_changed_or_deleted_by_the_application_role(table):
    app_role = settings.database_url.split("//")[1].split(":")[0]
    for priv in ("UPDATE", "DELETE", "TRUNCATE"):
        assert owner_query("SELECT has_table_privilege(:r, :t, :p)", r=app_role, t=f"public.{table}", p=priv)[0][0] is False, f"{app_role} can {priv} {table}"


def test_secrets_are_never_returned_by_the_session_endpoint():
    s = make_business("Leak Probe")
    body = s.get("/auth/me").text.lower()
    for needle in ("password_hash", "token_hash", "refresh_token", "secret", "api_key", "$argon2"):
        assert needle not in body, needle


# --------------------------------------------------------------------------------------------- logs

def test_access_logs_never_keep_oauth_codes_or_tokens_from_query_strings():
    import logging

    from app.core import monitoring

    assert monitoring.redact_url("/api/v1/google/callback?code=4/0AbC-secret&state=abc.def&scope=x") == "/api/v1/google/callback?code=[redacted]&state=[redacted]&scope=x"
    assert monitoring.redact_url("/api/v1/x?token=SECRET123") == "/api/v1/x?token=[redacted]"
    assert monitoring.redact_url("/api/v1/billing/plans") == "/api/v1/billing/plans"
    monitoring.redact_access_logs()
    monitoring.redact_access_logs()  # idempotent: one filter only
    lg = logging.getLogger("uvicorn.access")
    assert sum(1 for f in lg.filters if type(f).__name__ == "_RedactAccessLog") == 1
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", "/api/v1/auth/google/callback?code=SECRET&state=S2", "1.1", 303), None)
    assert all(f.filter(rec) for f in lg.filters)
    assert "SECRET" not in rec.getMessage() and "S2" not in rec.getMessage() and "[redacted]" in rec.getMessage()


# --------------------------------------------------------------------------------------------- production topology: the site and the API are different hosts

def test_cross_origin_browser_calls_work_for_the_site_and_only_the_site(monkeypatch):
    """Production: flowqr.site (Vercel) calls api.flowqr.site. The API must answer the preflight for the listed origins with credentials, refuse everyone else, and expose the response
    headers the frontend reads. (The CORS middleware reads its origins at start-up, so this builds an app with the production list.)"""
    import re as _re
    from pathlib import Path as _P

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    src = (_P(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    exposed = _re.search(r"expose_headers=\[(.*?)\]", src, _re.S).group(1)
    exposed = [h.strip().strip('"') for h in exposed.split(",") if h.strip()]
    # every custom header the API emits must be exposed, or the browser hides it from the frontend
    emitted = set()
    for f in (_P(__file__).resolve().parents[1] / "app").rglob("*.py"):
        if f.name == "integrations.py" and f.parent.name == "whatsapp":
            continue  # its X-FlowQR-* names are headers on webhook REQUESTS we send to a business's own server, not responses a browser reads
        emitted |= set(_re.findall(r"X-FlowQR-[A-Za-z-]+", f.read_text(encoding="utf-8")))
    assert emitted <= set(exposed), f"headers the API sends but the browser would hide: {sorted(emitted - set(exposed))}"
    assert "Content-Disposition" in exposed

    app2 = FastAPI()
    app2.add_middleware(CORSMiddleware, allow_origins=["https://flowqr.site", "https://www.flowqr.site"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                        allow_headers=["Content-Type", "X-CSRF-Token", "X-Tenant-Id"], expose_headers=exposed)

    @app2.get("/x")
    def x():
        return {"ok": True}

    c = TestClient(app2)
    for origin in ("https://flowqr.site", "https://www.flowqr.site"):
        r = c.options("/x", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-csrf-token"})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin and r.headers["access-control-allow-credentials"] == "true"
    for evil in ("https://evil.example", "https://flowqr.site.evil.example", "http://flowqr.site", "https://api.flowqr.site"):
        r = c.options("/x", headers={"Origin": evil, "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in r.headers, evil
    assert "x-flowqr-not-for-print" in c.get("/x", headers={"Origin": "https://flowqr.site"}).headers["access-control-expose-headers"].lower()
