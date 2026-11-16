"""Platform admin: user directory + login check + support actions. The verdict is checked against what the REAL login endpoint does."""
from app.services import mailer
from tests.conftest import Session, make_business, make_user, owner_exec, owner_query


def real_login(email, password="Str0ngPassw0rd!"):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, base_url="http://testserver").post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def test_only_platform_admins_can_use_the_user_tools(biz_a, client):
    assert biz_a.get("/admin/users").status_code == 403
    assert biz_a.post("/admin/users/lookup", json={"email": "x@example.com"}).status_code == 403
    assert client.get("/api/v1/admin/users").status_code == 401


def test_login_check_matches_what_login_really_does(admin, biz_a):
    # an ordinary working account
    r = admin.post("/admin/users/lookup", json={"email": biz_a.email.upper()}).json()
    assert r["exists"] and r["login"]["can_log_in"] and real_login(biz_a.email) == 200
    assert r["user"]["businesses"] == 1 and r["businesses"][0]["role"] == "owner" and r["user"]["email_verified"]
    # never returns secrets
    flat = str(r)
    assert "password_hash" not in flat and "token" not in flat.lower().replace("token_", "")

    # no such account
    n = admin.post("/admin/users/lookup", json={"email": "nobody-here@example.com"}).json()
    assert n["exists"] is False and not n["login"]["can_log_in"] and real_login("nobody-here@example.com") == 401
    assert admin.post("/admin/users/lookup", json={"email": "not-an-email"}).status_code == 422

    # deactivated: the check says refused, and the real login agrees
    uid = r["user"]["id"]
    assert admin.patch(f"/admin/users/{uid}", json={"is_active": False}).status_code == 204
    d = admin.post("/admin/users/lookup", json={"email": biz_a.email}).json()
    assert not d["login"]["can_log_in"] and "deactivated" in d["login"]["reasons"][0] and real_login(biz_a.email) == 401
    admin.patch(f"/admin/users/{uid}", json={"is_active": True})
    assert real_login(biz_a.email) == 200

    # an account with no way to sign in
    owner_exec("UPDATE users SET password_hash = NULL, google_sub = NULL WHERE id = :u", u=uid)
    z = admin.post("/admin/users/lookup", json={"email": biz_a.email}).json()
    assert not z["login"]["can_log_in"] and "nothing to log in with" in z["login"]["reasons"][0] and real_login(biz_a.email) == 401
    # Google-only: not refused, but explained
    owner_exec("UPDATE users SET google_sub = 'g-123' WHERE id = :u", u=uid)
    g = admin.post("/admin/users/lookup", json={"email": biz_a.email}).json()
    assert g["login"]["can_log_in"] and any("Google-only" in x for x in g["login"]["notes"]) and g["user"]["google_linked"] and not g["user"]["has_password"]

    acts = {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE action = 'admin.user_lookup'")}
    assert acts == {"admin.user_lookup"}  # every lookup is on record, found or not


def test_lookup_notes_suspended_business_and_pending_invitation(admin, biz_a):
    admin.post(f"/admin/tenants/{biz_a.tenant_id}/suspend", json={"reason": "test"})
    r = admin.post("/admin/users/lookup", json={"email": biz_a.email}).json()
    assert r["login"]["can_log_in"] and any("suspended" in n for n in r["login"]["notes"]) and r["businesses"][0]["suspended"]
    admin.post(f"/admin/tenants/{biz_a.tenant_id}/unsuspend")
    invited = "invited-not-registered@example.com"
    assert biz_a.post("/staff/invitations", json={"email": invited, "role": "staff"}).status_code == 201
    n = admin.post("/admin/users/lookup", json={"email": invited}).json()
    assert n["exists"] is False and n["pending_invitations"][0]["role"] == "staff"


def test_directory_search_filters_and_counts(admin, biz_a, biz_b):
    everyone = admin.get("/admin/users", params={"limit": 200}).json()
    assert everyone["total"] >= 3 and everyone["totals"]["all"] == everyone["total"]
    row = next(u for u in everyone["items"] if u["email"] == biz_a.email)
    assert row["businesses"] == 1 and row["business_names"] and "password" not in str(row).lower().replace("has_password", "")
    assert [u["email"] for u in admin.get("/admin/users", params={"search": biz_b.email[:12]}).json()["items"]] == [biz_b.email]
    by_business = admin.get("/admin/users", params={"search": biz_a.get("/tenant").json()["name"]}).json()["items"]
    assert biz_a.email in [u["email"] for u in by_business]
    assert all(u["is_platform_admin"] for u in admin.get("/admin/users", params={"state": "admin"}).json()["items"])
    assert admin.get("/admin/users", params={"state": "bogus"}).status_code == 422


def test_support_actions_are_audited_and_safe(admin, biz_a):
    me = admin.post("/admin/users/lookup", json={"email": biz_a.email}).json()["user"]
    uid = me["id"]
    assert biz_a.get("/auth/me").status_code == 200
    r = admin.post(f"/admin/users/{uid}/revoke-sessions").json()
    assert r["revoked"] >= 1 and biz_a.get("/auth/me").status_code == 401  # signed out everywhere
    assert real_login(biz_a.email) == 200  # but not locked out
    owner_exec("UPDATE users SET email_verified_at = NULL WHERE id = :u", u=uid)
    assert admin.post(f"/admin/users/{uid}/verify-email").status_code == 204
    assert admin.get(f"/admin/users/{uid}").json()["user"]["email_verified"] is True
    mailer.OUTBOX.clear()
    s = admin.post(f"/admin/users/{uid}/send-reset").json()
    assert s["sent"] and s["to"] == biz_a.email
    mail = [m for m in mailer.OUTBOX if m["to"] == biz_a.email][-1]
    assert "reset-password?token=" in mail["body"]
    assert "token" not in str(s).replace("expires_minutes", "")  # the admin never sees the link or the token
    for _ in range(3):
        admin.post(f"/admin/users/{uid}/send-reset")
    assert admin.post(f"/admin/users/{uid}/send-reset").status_code == 429
    acts = {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :u", u=uid)}
    assert {"admin.user_lookup", "admin.user_revoke_sessions", "admin.user_verify_email", "admin.user_send_reset"} <= acts
    assert admin.post(f"/admin/users/00000000-0000-0000-0000-000000000000/revoke-sessions").status_code == 404
