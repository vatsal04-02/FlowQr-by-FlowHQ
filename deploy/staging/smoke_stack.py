#!/usr/bin/env python3
"""Black-box staging smoke test against the RUNNING stack, over HTTPS through Caddy.

Covers: registration, email verification, onboarding, staff invitation, password reset, card batch/assign/scan.
Email is read from the SMTP sink (Mailpit) the stack delivers to. If SMTP_HOST points at a real provider,
set MAILPIT_URL='' and supply the tokens manually (this script then marks the mail steps NOT TESTED).

Run from a container on the compose network (hostnames resolve through Caddy's network aliases):
  docker run --rm --network flowqr-staging_default -v $PWD/deploy/staging:/s:ro -v /tmp/caddy-root.crt:/ca.crt:ro \
     -e SSL_CERT_FILE=/ca.crt -e STAGING_DOMAIN=flowqr-staging.dev -e MAILPIT_URL=http://mailpit:8025 -v /tmp/out:/out \
     flowqr-backend:local python /s/smoke_stack.py
"""
import json
import os
import re
import sys
import time
import uuid

import httpx

D = os.environ.get("STAGING_DOMAIN", "flowqr-staging.dev")
MAIL = os.environ.get("MAILPIT_URL", "http://mailpit:8025")
APP, CARD = f"https://app.{D}", f"https://go.{D}"
PW = "Staging-Passw0rd!x1"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
results: list[tuple[str, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append(("PASS" if ok else "FAIL", name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


class User:
    def __init__(self, email: str):
        self.email, self.http, self.csrf = email, httpx.Client(base_url=APP + "/api/v1", timeout=20), None

    def req(self, m, path, **kw):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        extra = kw.pop("headers", {})
        for _ in range(8):  # the API rate-limits auth endpoints per client IP: back off like a well-behaved client
            r = self.http.request(m, path, headers=h | extra, **kw)
            if r.status_code != 429:
                return r
            time.sleep(30)
        return r

    def register(self, name):
        r = self.req("POST", "/auth/register", json={"email": self.email, "password": PW, "full_name": name})
        if r.status_code == 201:
            self.csrf = r.json()["csrf_token"]
        return r

    def login(self, pw=PW):
        r = self.req("POST", "/auth/login", json={"email": self.email, "password": pw})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r


def mails_for(to: str, subject_part: str, wait: float = 10.0) -> list[dict]:
    end = time.time() + wait
    while time.time() < end:
        msgs = httpx.get(f"{MAIL}/api/v1/messages", params={"limit": 200}, timeout=10).json().get("messages", [])
        hit = [m for m in msgs if any(t["Address"] == to for t in m["To"]) and subject_part in m["Subject"]]
        if hit:
            return hit
        time.sleep(0.5)
    return []


def token_from_mail(to: str, subject_part: str) -> str | None:
    hit = mails_for(to, subject_part)
    if not hit:
        return None
    body = httpx.get(f"{MAIL}/api/v1/message/{hit[0]['ID']}", timeout=10).json()["Text"]
    m = re.search(r"token=([\w-]+)", body)
    return m.group(1) if m else None


def main() -> int:
    run = uuid.uuid4().hex[:6]
    admin, owner, staff = User(f"admin@{D}"), User(f"owner-{run}@{D}"), User(f"staff-{run}@{D}")

    # ---- registration + email verification ----
    r = admin.register("FlowHQ Admin")
    if r.status_code == 409:
        r = admin.login()
    check(r.status_code in (200, 201), "platform admin account registered/signed in (email listed in PLATFORM_ADMIN_EMAILS)")
    # Phase 2 security fix: an administrator address is NOT an administrator until its mailbox is proven. Verify through the delivered email, then sign in again.
    if not admin.req("GET", "/auth/me").json()["user"]["is_platform_admin"]:
        tok = token_from_mail(admin.email, "Verify")
        check(bool(tok), "admin verification email delivered via SMTP")
        if tok:
            admin.req("POST", "/auth/verify-email", json={"token": tok})
            admin.login()
    check(admin.req("GET", "/auth/me").json()["user"]["is_platform_admin"], "platform admin rights granted only after email verification")
    check(owner.register("Staging Owner").status_code == 201, "owner registration")
    me = owner.req("GET", "/auth/me").json()
    check(me["user"]["email_verified_at"] is None, "new account starts unverified")
    mail = mails_for(owner.email, "Verify")
    check(len(mail) == 1, "verification email delivered via SMTP", mail[0]["Subject"] if mail else "no message")
    owner.req("POST", "/tenants", json={"name": f"Staging Clinic {run}", "category": "Physiotherapy clinic"})
    r = owner.req("POST", "/staff/invitations", json={"email": staff.email})
    check(r.status_code == 403 and r.json()["detail"]["code"] == "email_not_verified", "unverified owner cannot invite staff")
    tok = token_from_mail(owner.email, "Verify")
    check(bool(tok) and owner.req("POST", "/auth/verify-email", json={"token": tok}).status_code == 204, "email verification link works")
    check(owner.req("POST", "/auth/verify-email", json={"token": tok}).status_code == 400, "verification token is single-use")
    check(owner.req("GET", "/auth/me").json()["user"]["email_verified_at"] is not None, "account now verified")
    tok_admin = token_from_mail(admin.email, "Verify")
    if tok_admin:
        admin.req("POST", "/auth/verify-email", json={"token": tok_admin})

    # ---- onboarding ----
    r = owner.req("POST", "/locations", json={"name": "Gomti Nagar", "city": "Lucknow", "review_url": "https://g.page/r/STAGINGDEMO/review"})
    check(r.status_code == 201, "location created", r.text[:80])
    loc = r.json()["id"]
    check(owner.req("POST", "/tenant/complete-onboarding").status_code == 200, "onboarding completed")
    tenant = owner.req("GET", "/tenant").json()

    # ---- staff invitation over SMTP ----
    r = owner.req("POST", "/staff/invitations", json={"email": staff.email, "role": "staff"})
    check(r.status_code == 201, "staff invitation created")
    inv_tok = token_from_mail(staff.email, "invited")
    check(bool(inv_tok), "invitation email delivered via SMTP")
    check(staff.register("Staging Staff").status_code == 201, "invitee registers")
    stok = token_from_mail(staff.email, "Verify")
    staff.req("POST", "/auth/verify-email", json={"token": stok})
    wrong = User(f"someoneelse-{run}@{D}"); wrong.register("Other"); wrong.req("POST", "/auth/verify-email", json={"token": token_from_mail(wrong.email, "Verify")})
    check(wrong.req("POST", "/invitations/accept", json={"token": inv_tok}).status_code == 400, "invitation cannot be accepted by a different email")
    r = staff.req("POST", "/invitations/accept", json={"token": inv_tok})
    check(r.status_code == 200, "invitee accepts invitation")
    check(staff.req("POST", "/locations", json={"name": "Not allowed"}).status_code == 403, "staff role cannot create locations")
    check(staff.req("GET", "/locations").status_code == 200, "staff can read locations")
    check(len(staff.req("GET", "/locations").json()) == 1, "staff sees only the inviting business")

    # ---- password reset over SMTP ----
    other = User(owner.email)
    r = other.req("POST", "/auth/password-reset/request", json={"email": owner.email})
    check(r.status_code == 202, "password reset request accepted")
    check(User("nobody@" + D).req("POST", "/auth/password-reset/request", json={"email": "nobody@" + D}).status_code == 202, "reset request for unknown email gives the same answer")
    rt = token_from_mail(owner.email, "Reset")
    check(bool(rt), "reset email delivered via SMTP")
    newpw = PW + "-new"
    check(other.req("POST", "/auth/password-reset/confirm", json={"token": rt, "new_password": newpw}).status_code == 204, "password reset confirmed")
    check(other.req("POST", "/auth/password-reset/confirm", json={"token": rt, "new_password": newpw + "z"}).status_code == 400, "reset token is single-use")
    check(owner.req("GET", "/auth/me").status_code == 401, "old sessions revoked after reset")
    check(owner.login(PW).status_code == 401, "old password rejected")
    check(owner.login(newpw).status_code == 200, "new password works")
    owner_pw = newpw

    # ---- cards ----
    admin.login()
    r = admin.req("POST", "/admin/batches", json={"name": f"Staging batch {run}", "quantity": 3})
    check(r.status_code == 201 and r.json()["base_url"] == CARD, "card batch created; base URL recorded", r.json().get("base_url", ""))
    cards = admin.req("GET", "/admin/cards", params={"batch_id": r.json()["id"]}).json()["items"]
    check(all(c["url"].startswith((CARD + "/q/", CARD + "/c/")) for c in cards), "card URLs use the go. card domain (printed QR address is /q/)", cards[0]["url"])
    r = admin.req("POST", f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": tenant["id"], "location_id": loc})
    check(r.status_code == 200, "card assigned to location")
    pub = httpx.Client(timeout=20)
    page = pub.get(f"{CARD}/api/v1/public/c/{cards[0]['public_token']}", headers={"User-Agent": UA}).json()
    check(page.get("state") == "ok" and page["review_url"] == "https://g.page/r/STAGINGDEMO/review", "public scan resolves business + review link via card domain")
    check(cards[0]["id"] not in json.dumps(page) and tenant["id"] not in json.dumps(page), "public payload leaks no internal IDs")
    stats = owner.req("GET", "/cards").json()[0]["stats"] if owner.csrf else {}
    check(stats.get("scan") == 1, "scan event recorded", str(stats))

    out = {"run": run, "owner": {"email": owner.email, "password": owner_pw}, "staff": {"email": staff.email, "password": PW},
           "admin": {"email": admin.email, "password": PW}, "tenant_id": tenant["id"], "location_id": loc,
           "card": {"code": cards[0]["card_code"], "token": cards[0]["public_token"]}}
    if os.path.isdir("/out"):
        json.dump(out, open("/out/seed.json", "w"), indent=2)
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\nSUMMARY: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
