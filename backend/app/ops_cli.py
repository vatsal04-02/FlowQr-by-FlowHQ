"""Operator commands for going live (registered in app/cli.py).

  python -m app.cli preflight [--smtp-test you@example.com] [--sentry-test]
      Checks the real configuration end to end: production guard, secrets, database + migrations, Redis, SMTP login, Razorpay keys, AI key and model,
      Google OAuth settings, error reporting, backups. Read-only except the two opt-in tests. Exit 1 when something that blocks launch is wrong.
  python -m app.cli set-admin-password --email you@company.com
      Sets a new platform-admin password (typed twice, never shown or logged) and signs that account out everywhere.
  python -m app.cli google-write-test --connection ID --location locations/N [--post] [--photo] [--profile] [--reply-review ID --reply-text "..."]
        [--execute --confirm-location locations/N --confirm-title "Exact Profile Title"]   (also needs FLOWQR_LIVE_WRITE_AUTHORIZED=locations/N)
      The controlled LIVE write test. Dry run by default: prints exactly what would be sent and sends nothing.

Secrets are never printed. Nothing here is run by the app itself.
"""
from __future__ import annotations

import argparse
import getpass
import io
import smtplib
import ssl
import sys
import uuid

import httpx
from sqlalchemy import select, text, update

from app.core.config import config_problems, settings

PASS, FAIL, WARN, MANUAL, SKIP = "PASS", "FAIL", "WARN", "MANUAL", "SKIP"


class Report:
    def __init__(self) -> None:
        self.counts = {PASS: 0, FAIL: 0, WARN: 0, MANUAL: 0, SKIP: 0}

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.counts[status] += 1
        print(f"  {status:<7} {name:<34} {detail}"[:210])


def _http(method: str, url: str, **kw) -> httpx.Response | None:
    try:
        return httpx.request(method, url, timeout=12, **kw)
    except httpx.HTTPError:
        return None


def preflight(args: argparse.Namespace) -> int:
    r = Report()
    hardened = settings.hardened
    print(f"FlowQR preflight: APP_ENV={settings.app_env} ({'strict production rules apply' if hardened else 'development: problems below are warnings, but would STOP a production boot'})\n")

    print("Configuration")
    probs = config_problems(settings)
    if probs:
        for p in probs:
            r.add(FAIL if hardened else WARN, "production guard", p[:150])
    else:
        r.add(PASS, "production guard", "no dev secrets, insecure cookies, localhost URLs or missing SMTP/Razorpay pairs")
    try:
        from app.core.security import get_cipher
        c = get_cipher()
        assert c.decrypt(c.encrypt("x")) == "x"
        r.add(PASS, "TOKEN_ENCRYPTION_KEY", "valid; round trip works")
    except Exception:
        r.add(FAIL, "TOKEN_ENCRYPTION_KEY", "not a valid Fernet key (generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")")
    r.add(PASS if settings.cookie_secure else (FAIL if hardened else WARN), "secure cookies", f"COOKIE_SECURE={settings.cookie_secure}")

    print("\nServices")
    try:
        from app.core.db import system_session
        from app.services import ops
        db = system_session()
        try:
            db.execute(text("SELECT 1"))
            r.add(PASS, "database", "reachable")
            m = ops.check_migrations(db)
            r.add({"ok": PASS, "unknown": WARN}.get(m["status"], FAIL), "migrations", m["detail"])
            admins = settings.platform_admin_email_set
            from app.models import User
            rows = db.execute(select(User.email, User.password_hash, User.last_login_at).where(User.email.in_(admins))).all() if admins else []
            found = {e for e, _, _ in rows}
            for e in sorted(admins - found):
                r.add(WARN, f"admin {e}", "listed in PLATFORM_ADMIN_EMAILS but no account yet (it becomes admin when registered)")
            for e, ph, last in rows:
                r.add(MANUAL, f"admin {e}", ("has a password; " if ph else "no password; ") + f"last login {last:%Y-%m-%d}" if last else "never signed in")
            r.add(MANUAL, "admin password", "run `python -m app.cli set-admin-password --email <you>` so no password issued earlier (chat, notes) is still valid")
        finally:
            db.close()
    except Exception as exc:
        r.add(FAIL, "database", f"cannot connect ({type(exc).__name__})")
    from app.services import ops
    r.add(PASS if ops._redis() else FAIL, "redis", "reachable" if ops._redis() else "not reachable")

    print("\nEmail")
    if not settings.smtp_host:
        r.add(FAIL if hardened else WARN, "SMTP", "SMTP_HOST is not set: verification, invitations and password resets cannot be delivered")
    else:
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.ehlo()
                if settings.smtp_starttls:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
            r.add(PASS, "SMTP login", f"{settings.smtp_host}:{settings.smtp_port} accepted the connection and credentials (no mail sent)")
        except (smtplib.SMTPException, OSError) as exc:
            r.add(FAIL, "SMTP login", f"{type(exc).__name__}: check host, port, STARTTLS and credentials")
        if args.smtp_test:
            from app.services.mailer import send_email
            ok = send_email(args.smtp_test, "FlowQR email test", "If you can read this, FlowQR can send you email (verification, invitations, password resets, alerts).")
            r.add(PASS if ok else FAIL, "SMTP test message", f"handed to the server for {args.smtp_test}; now confirm it arrived (and is not in spam)" if ok else "the server refused it")
        else:
            r.add(MANUAL, "email delivery", "re-run with --smtp-test you@example.com and confirm the message lands in the inbox, not spam; add SPF/DKIM/DMARC for the sending domain")

    print("\nPayments")
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        resp = _http("GET", "https://api.razorpay.com/v1/payments", params={"count": 1}, auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        mode = "LIVE" if settings.razorpay_key_id.startswith("rzp_live_") else "TEST"
        r.add(PASS if resp is not None and resp.status_code == 200 else FAIL, "Razorpay keys", f"{mode} keys accepted by Razorpay" if resp is not None and resp.status_code == 200 else f"Razorpay answered {resp.status_code if resp is not None else 'no response'}")
        r.add(PASS if settings.razorpay_webhook_secret else FAIL, "webhook secret", "set" if settings.razorpay_webhook_secret else "RAZORPAY_WEBHOOK_SECRET missing")
        r.add(MANUAL, "webhook endpoint", f"In Razorpay: Webhooks > add {settings.frontend_url}/api/v1/billing/razorpay/webhook with the same secret; events payment.captured/failed, subscription.*, then send a test event")
    else:
        r.add(FAIL if hardened else WARN, "Razorpay", "keys not set: paid plans cannot be bought")

    print("\nAI")
    if settings.ai_provider == "gemini" and settings.gemini_api_key:
        resp = _http("GET", f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}", headers={"x-goog-api-key": settings.gemini_api_key})
        r.add(PASS if resp is not None and resp.status_code == 200 else FAIL, f"Gemini model {settings.gemini_model}", "key valid and model exists" if resp is not None and resp.status_code == 200 else f"Google answered {resp.status_code if resp is not None else 'no response'}")
    elif settings.ai_configured:
        r.add(WARN, f"AI provider {settings.ai_provider}", "configured; not probed from here")
    else:
        r.add(FAIL if hardened else WARN, "AI provider", "no key: replies, posts and the growth agent are off")
    r.add(PASS if settings.ai_monthly_budget_usd > 0 else WARN, "AI monthly budget", f"${settings.ai_monthly_budget_usd:.2f}" if settings.ai_monthly_budget_usd > 0 else "AI_MONTHLY_BUDGET_USD not set; also set a billing alert in the provider console")

    print("\nGoogle")
    r.add(PASS if settings.google_configured else FAIL, "Business Profile OAuth client", "set" if settings.google_configured else "GOOGLE_CLIENT_ID/SECRET missing")
    r.add(PASS if settings.google_redirect_uri.startswith("https://") else (FAIL if hardened else WARN), "redirect URI", settings.google_redirect_uri)
    r.add(MANUAL, "OAuth consent screen", "Publish the app (not 'Testing', where refresh tokens expire after 7 days) and complete Google's verification for the business.manage sensitive scope; see docs/GOOGLE_SETUP.md")
    r.add(MANUAL, "Business Profile API quota", "Confirm access is approved (quota above 0) for the Cloud project; run `google-smoke` for the live read check")

    print("\nMonitoring and backups")
    r.add(PASS if settings.sentry_dsn else (FAIL if hardened else WARN), "error reporting", "SENTRY_DSN set" if settings.sentry_dsn else "SENTRY_DSN not set")
    if args.sentry_test:
        from app.core import monitoring
        monitoring.init("cli")
        monitoring.capture_message("FlowQR preflight test event (safe to ignore)", "info", where="preflight")
        import sentry_sdk
        sentry_sdk.flush(5)
        r.add(PASS if monitoring.enabled() else FAIL, "Sentry test event", "sent: confirm it appears in your Sentry project" if monitoring.enabled() else "not sent (no DSN or SDK)")
    b = ops.check_backup()
    r.add({"ok": PASS, "warn": WARN}.get(b["status"], FAIL), "backups", b["detail"] + (". " + b["action"] if b["action"] else ""))

    print(f"\n{r.counts[PASS]} passed, {r.counts[FAIL]} failed, {r.counts[WARN]} warnings, {r.counts[MANUAL]} need you (manual).")
    if r.counts[FAIL]:
        print("NOT READY: fix the FAIL lines above.")
        return 1
    print("No blocking failures. Work through the MANUAL and WARN lines before real customers.")
    return 0


def set_admin_password(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from app.core.db import system_session
    from app.core.security import hash_password
    from app.models import AuthSession, User
    from app.models.base import utcnow
    from app.schemas.auth import SetPasswordIn
    from app.services.audit import audit

    email = args.email.strip().lower()
    db = system_session()
    try:
        u = db.scalar(select(User).where(User.email == email))
        if not u or not u.is_platform_admin:
            print("No platform-admin account with that email. Nothing changed.")
            return 1
        pw = getpass.getpass("New password (not shown): ")
        if pw != getpass.getpass("Repeat it: "):
            print("The two entries differ. Nothing changed.")
            return 1
        try:
            SetPasswordIn(new_password=pw)
        except ValidationError as exc:
            print("Rejected: " + "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()))
            return 1
        u.password_hash = hash_password(pw)
        n = db.execute(update(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow())).rowcount
        audit(db, action="auth.password_changed", user_id=u.id, meta={"source": "cli"})
        db.commit()
        print(f"Password changed for {email}. {n} signed-in session(s) were ended. Store the password in a password manager, not in chat or notes.")
        return 0
    finally:
        db.close()


def _png(size: int = 480) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (size, size), (240, 240, 245))
    ImageDraw.Draw(im).text((20, size // 2), "FlowQR connection test - safe to ignore", fill=(60, 60, 70))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


LIVE_ENV = "FLOWQR_LIVE_WRITE_AUTHORIZED"
TEST_MARK = " [FlowQR write test]"


class _Report:
    """What happened, step by step. `verified` is True only when the resource was READ BACK from Google and matched; a call that merely returned 200 is not verified."""

    def __init__(self, mode: str, location: str) -> None:
        self.mode, self.location, self.results = mode, location, []

    def add(self, name: str, status: str, detail: str = "", *, verified: bool = False) -> bool:
        self.results.append({"step": name, "status": status, "verified_by_read_back": verified, "detail": detail[:300]})
        print(f"  {status:<5} {name}" + (" [read back from Google]" if verified else "") + (f": {detail}" if detail else ""))
        return status == PASS

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r["status"] == FAIL)

    def as_dict(self) -> dict:
        from datetime import datetime, timezone

        return {"mode": self.mode, "location": self.location, "finished_at": datetime.now(timezone.utc).isoformat(), "failed": self.failed, "results": self.results,
                "note": "mode 'live' = real Google calls; mode 'mocked' = a test double, NOT evidence that Google accepts anything."}


def google_write_test(args: argparse.Namespace, *, provider=None, access_token: str | None = None, sleep=None, report_to: _Report | None = None) -> int:
    """Controlled LIVE write test on an explicitly authorised TEST profile. Four steps, each VERIFIED BY READING THE RESOURCE BACK FROM GOOGLE, each cleaned up:

      post     create a STANDARD post -> list posts and see it with the same text -> delete it -> list and see it gone
      photo    upload a generated test image -> read the media item back -> delete it -> confirm it is gone
      profile  set the description to (original + a marker) -> read it back twice -> restore the original -> read that back too
      reply    publish the given reply to the given review -> read the review back and compare the reply -> delete the reply -> confirm it is gone

    Safety: dry run unless --execute. To execute, ALL of: the env var FLOWQR_LIVE_WRITE_AUTHORIZED equals the location (a person deliberately exported it),
    --confirm-location repeats it, and --confirm-title repeats the profile's real title exactly as Google returns it (so a human has looked at which
    profile this is). `provider=` / `access_token=` exist only so the automated tests can run this same code against a test double; the report then
    says "mocked", never "live"."""
    import os
    import time

    from app.services import google as g
    from app.services.google.smoke import _refresh_token

    sleep = sleep or time.sleep
    mocked = provider is not None
    steps = [s for s, on in (("post", args.post), ("photo", args.photo), ("profile", getattr(args, "profile", False)), ("reply", bool(args.reply_review))) if on]
    if not steps:
        print("Choose at least one of --post, --photo, --profile, --reply-review ID --reply-text TEXT.")
        return 2
    if args.reply_review and not args.reply_text:
        print("--reply-text is required with --reply-review.")
        return 2
    post_text = "FlowQR connection test. Safe to ignore; this post is removed automatically."
    print("FlowQR -> Google WRITE test " + ("(MOCKED PROVIDER: no Google call is made)" if mocked else "(LIVE)") + ("" if args.execute else " - DRY RUN: nothing will be sent"))
    print(f"Location: {args.location}")
    plan = {
        "post": f"create a STANDARD post \"{post_text}\", read the post list back, DELETE it, read the list back",
        "photo": "upload a generated 480x480 grey image (category ADDITIONAL), read the media item back, DELETE it, confirm it is gone",
        "profile": f"set the description to (current text + \"{TEST_MARK.strip()}\"), read it back, RESTORE the original, read that back",
        "reply": f"publish a reply to review {args.reply_review} (PUBLIC while it exists), read the review back, "
                 + ("KEEP it (--keep-reply)" if getattr(args, "keep_reply", False) else "DELETE the reply, confirm it is gone"),
    }
    for s in steps:
        print(f"  {s:<8}: {plan[s]}")
    if not args.execute:
        print(f"\nNOT EXECUTED. Use a throwaway or test location you own. To run: add --execute --confirm-location <same locations/N> --confirm-title \"<exact profile title>\" "
              f"and export {LIVE_ENV}=<same locations/N>.")
        return 0
    if args.confirm_location != args.location:
        print("\nRefused: --confirm-location must repeat --location exactly. Nothing was sent.")
        return 2
    if os.environ.get(LIVE_ENV) != args.location:
        print(f"\nRefused: {LIVE_ENV} is not set to this location. Export it yourself to say this is an authorised test profile. Nothing was sent.")
        return 2
    if not mocked:
        token_value, source = _refresh_token(args.connection)
        if not token_value:
            print("BLOCKED: no refresh token (--connection ID or GOOGLE_SMOKE_REFRESH_TOKEN). Nothing was sent.")
            return 2
        provider = g.get_google_provider()
        access_token = provider.refresh_access_token(token_value).access_token
    at = access_token or "mock-token"
    account = next((a.name for a in provider.list_accounts(at) for loc in provider.list_locations(at, a.name) if loc.name == args.location), None)
    if not account:
        print("The location was not found on this Google account. Nothing was sent.")
        return 2
    details = provider.get_location_details(at, args.location)
    title = details.get("title") or ""
    print(f"Profile title as Google returns it: {title!r}")
    if getattr(args, "confirm_title", None) != title or not title:
        print("\nRefused: --confirm-title must repeat that title exactly. Check this is the TEST profile. Nothing was sent.")
        return 2

    rep = report_to or _Report("mocked" if mocked else "live", args.location)

    def guarded(name: str, fn) -> bool:
        try:
            ok, detail = fn()
        except (g.GoogleError, AssertionError) as exc:
            return rep.add(name, FAIL, f"{type(exc).__name__} {getattr(exc, 'status', '')} {str(exc)[:160]}")
        return rep.add(name, PASS if ok else FAIL, detail, verified=ok)

    def expect(cond: bool, message: str) -> None:
        if not cond:
            raise AssertionError(message)

    if "post" in steps:
        made: dict = {}

        def create():
            made.update(p=provider.create_post(at, account, args.location, {"summary": post_text, "language": "en", "topic_type": "STANDARD"}))
            sleep(2)
            listed = [p for p in provider.list_posts(at, account, args.location) if p.get("name") == made["p"].get("name")]
            expect(bool(listed), "Google does not list the post that create returned")
            expect(" ".join((listed[0].get("summary") or "").split()) == post_text, "the post text Google holds differs from what was sent")
            return True, f"Google lists it with the same text ({made['p']['name'][-24:]})"

        if guarded("post: create, then read it back", create) and made.get("p", {}).get("name"):
            def remove():
                provider.delete_post(at, made["p"]["name"])
                sleep(2)
                expect(not any(p.get("name") == made["p"]["name"] for p in provider.list_posts(at, account, args.location)), "the post is still listed after delete")
                return True, "gone from Google's list"

            guarded("post: delete, then confirm it is gone", remove)
    if "photo" in steps:
        made = {}

        def upload():
            made.update(m=provider.upload_media_bytes(at, account, args.location, _png(), "image/png", "ADDITIONAL", "FlowQR connection test"))
            sleep(2)
            back = provider.get_media(at, made["m"]["name"])
            expect(back.get("name") == made["m"]["name"], "Google returns a different media item")
            expect(back.get("category") in (None, "ADDITIONAL"), f"Google reports category {back.get('category')}")
            return True, f"Google returns it ({made['m']['name'][-24:]}); live url present: {bool(back.get('google_url'))} (may stay empty while Google processes)"

        if guarded("photo: upload, then read it back", upload) and made.get("m", {}).get("name"):
            def remove_photo():
                provider.delete_media(at, made["m"]["name"])
                sleep(2)
                expect(not any(m.get("name") == made["m"]["name"] for m in provider.list_media(at, account, args.location)), "the photo is still listed after delete")
                return True, "gone from Google's list"

            guarded("photo: delete, then confirm it is gone", remove_photo)
    if "profile" in steps:
        original = (details.get("description") or "").strip()
        marked = (original + TEST_MARK)[:750]
        if len(original) + len(TEST_MARK) > 750:
            rep.add("profile: description round trip", SKIP, "the current description is too long to add a marker safely; nothing was changed")
        else:
            applied = {"on": False}

            def change():
                after = provider.update_location(at, args.location, {"description": marked})
                applied["on"] = True
                expect((after.get("description") or "").strip() == marked, "update_location's read-back does not show the new description")
                sleep(2)
                again = provider.get_location_details(at, args.location)
                expect((again.get("description") or "").strip() == marked, "a second, separate read does not show the new description")
                return True, "Google returned the new description on two separate reads"

            ok = guarded("profile: change description, then read it back", change)
            if applied["on"]:
                def restore():
                    after = provider.update_location(at, args.location, {"description": original})
                    sleep(2)
                    again = provider.get_location_details(at, args.location)
                    expect((again.get("description") or "").strip() == original, "the ORIGINAL description is not back; restore it by hand in Google Business Profile")
                    return True, "the original description is back, confirmed by a read"

                guarded("profile: restore the original, then read it back", restore)
            elif not ok:
                pass
    if "reply" in steps:
        def find_review():
            token = None
            for _ in range(10):
                page = provider.list_reviews(at, account, args.location, token)
                hit_ = next((rv for rv in page.reviews if rv.external_id == args.reply_review), None)
                if hit_ or not page.next_page_token:
                    return hit_
                token = page.next_page_token
            return None

        def reply():
            out = provider.reply_to_review(at, account, args.location, args.reply_review, args.reply_text) or {}
            sleep(2)
            rv = find_review()
            expect(rv is not None, "the review was not found when reading it back")
            expect(rv.reply_state != "REJECTED", f"Google REJECTED the reply ({getattr(rv, 'reply_policy_violation', None)})")
            expect((rv.reply_text or "").strip() == args.reply_text.strip() or rv.reply_state == "PENDING", "the reply Google holds differs from what was sent")
            return True, f"Google shows reply state {rv.reply_state or out.get('state')}"

        if guarded("reply: publish, then read the review back", reply) and not getattr(args, "keep_reply", False):
            def unreply():
                provider.delete_reply(at, account, args.location, args.reply_review)
                sleep(2)
                rv = find_review()
                expect(rv is not None and not (rv.reply_text or "").strip(), "the reply is still shown after delete")
                return True, "reply removed, confirmed by reading the review"

            guarded("reply: delete, then confirm it is gone", unreply)
    print("\nRESULT: " + ("all executed steps passed AND were read back from Google" if not rep.failed else f"{rep.failed} step(s) FAILED; see above") + ("  [MOCKED: not evidence about Google]" if mocked else ""))
    path = getattr(args, "report", None)
    if path:
        import json

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep.as_dict(), fh, indent=2)
        print(f"Report written to {path}")
    return 1 if rep.failed else 0


def autonomy_live_test(args: argparse.Namespace, *, provider=None, sleep=None, report_to: _Report | None = None) -> int:
    """Controlled LIVE test of the GOVERNED execution path (the one owners and the agent use), on an explicitly authorised TEST profile. Unlike google-write-test
    (which calls Google directly to learn what Google accepts), this goes through the real engine: policy -> person's authorisation -> claim -> write -> independent
    read-back -> tamper-evident history. Each step is only PASS if the engine itself reports `executed` (Google's profile shows the change) AND the history chain verifies.

      profile  edit the description (original + a marker) through executor.owner_edit, then restore the original the same way
      post     publish a marked STANDARD post through the governed publisher, then delete it the same way

    Safety is identical to google-write-test: dry run unless --execute; executing needs the env var FLOWQR_LIVE_WRITE_AUTHORIZED=<location>, --confirm-location and
    --confirm-title (the profile's real title). The acting person is the business owner recorded in FlowQR. `provider=` exists only so the automated tests can run this
    same code against a test double; the report then says "mocked", never "live"."""
    import os
    import time
    import uuid

    from sqlalchemy import select

    from app.core.db import SessionLocal, set_rls_context
    from app.models import AgentAction, GoogleConnection, GoogleLocation, Membership, Role, Tenant
    from app.services import google as g
    from app.services.agent import content_exec, executor, history
    from app.services.google.tokens import get_access_token

    sleep = sleep or time.sleep
    mocked = provider is not None
    steps = [s for s, on in (("profile", args.profile), ("post", args.post)) if on]
    if not steps:
        print("Choose at least one of --profile, --post.")
        return 2
    print("FlowQR GOVERNED-path test " + ("(MOCKED PROVIDER: no Google call is made)" if mocked else "(LIVE)") + ("" if args.execute else " - DRY RUN: nothing will be sent"))
    print(f"Location: {args.location}")
    plan = {"profile": f"edit the description to (current + \"{TEST_MARK.strip()}\") through the policy engine, require Google to show it on an independent read, then RESTORE the original the same way",
            "post": "publish a marked STANDARD post through the governed publisher, require Google to list it, then DELETE it the same way and require it gone"}
    for st in steps:
        print(f"  {st:<8}: {plan[st]}")
    if not args.execute:
        print(f"\nNOT EXECUTED. To run: add --execute --confirm-location <same locations/N> --confirm-title \"<exact profile title>\" and export {LIVE_ENV}=<same locations/N>.")
        return 0
    if args.confirm_location != args.location:
        print("\nRefused: --confirm-location must repeat --location exactly. Nothing was sent.")
        return 2
    if os.environ.get(LIVE_ENV) != args.location:
        print(f"\nRefused: {LIVE_ENV} is not set to this location. Export it yourself to say this is an authorised test profile. Nothing was sent.")
        return 2
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    try:
        conds = [GoogleLocation.google_location_name == args.location] + ([GoogleLocation.connection_id == args.connection] if args.connection else [])
        matches = db.scalars(select(GoogleLocation).where(*conds)).all()
        if len(matches) > 1:
            print("More than one connected business has that location name: pass --connection ID so the right one is used. Nothing was sent.")
            return 2
        gloc = matches[0] if matches else None
        conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
        if gloc is None or conn is None:
            print("That location is not connected in FlowQR (use --connection ID). Nothing was sent.")
            return 2
        tenant = db.get(Tenant, gloc.tenant_id)
        owner = db.scalar(select(Membership.user_id).where(Membership.tenant_id == tenant.id, Membership.role == Role.owner).limit(1))
        provider = provider or g.get_google_provider()
        at = get_access_token(db, conn, provider)
        details = provider.get_location_details(at, args.location)
        title = details.get("title") or ""
        print(f"Profile title as Google returns it: {title!r}")
        if getattr(args, "confirm_title", None) != title or not title:
            print("\nRefused: --confirm-title must repeat that title exactly. Check this is the TEST profile. Nothing was sent.")
            return 2
        rep = report_to or _Report("mocked" if mocked else "live", args.location)

        def chain_ok(action_id) -> bool:
            return bool(history.verify(db, action_id)["ok"])

        def last_executed(field_key):
            return db.scalar(select(AgentAction).where(AgentAction.tenant_id == tenant.id, AgentAction.field_key == field_key, AgentAction.status == "executed")
                             .order_by(AgentAction.created_at.desc()).limit(1))

        if "profile" in steps:
            original = (details.get("description") or "").strip()
            if len(original) < 2:
                rep.add("profile: needs an existing description to restore", FAIL, "this test profile has no description; add one first so it can be restored exactly")
            else:
                marked = (original + TEST_MARK)[:750]
                for label, value in (("profile: change through the engine, Google must show it", marked), ("profile: restore through the engine, Google must show it", original)):
                    res = executor.owner_edit(db, tenant, gloc, user_id=owner, role=Role.owner, changes={"description": value}, live=provider.get_location_details(at, args.location),
                                              provider=provider, sleep=sleep)
                    a = last_executed("description")
                    ok = not res["failed"] and "description" in res["applied"] and a is not None and a.verified_at is not None and chain_ok(a.id)
                    rep.add(label, PASS if ok else FAIL, (f"action {a.id}; history chain intact" if ok else f"failed: {res['failed']}"), verified=ok)
                    if not ok:
                        break
        if "post" in steps:
            text_ = "FlowQR governed-path test. Safe to ignore; this post is removed automatically."
            gl_ids = (gloc.google_account_name, gloc.google_location_name)
            made: dict = {}

            def create():
                made["r"] = provider.create_post(at, *gl_ids, {"summary": text_, "language": "en", "topic_type": "STANDARD"})
                return "done", {"name": made["r"].get("name"), "_gloc": gl_ids}

            out = content_exec.direct(db, kind="dpost", action_type="publish_content", tenant_id=tenant.id, gloc=gloc, user_id=owner, role=Role.owner, feature="gbp_posts",
                                      content={"summary": text_}, label="Google Post", send=create, verify=content_exec._verify_post(text_), provider=provider)
            ok = out["outcome"] == "done" and out.get("verified") is True and chain_ok(uuid.UUID(out["action_id"]))
            rep.add("post: publish through the engine, Google must list it", PASS if ok else FAIL, f"action {out.get('action_id')}; {out.get('detail') or ''}", verified=ok)
            name = (made.get("r") or {}).get("name")
            if name:
                sleep(2)

                def remove():
                    provider.delete_post(at, name)
                    return "done", {"name": name, "_gloc": gl_ids}

                def gone(prov, token, payload) -> dict:
                    still = any(p.get("name") == name for p in prov.list_posts(token, *gl_ids))
                    return {"matched": not still, "detail": "Google still lists the post." if still else "Google no longer lists the post."}

                out2 = content_exec.direct(db, kind="dpostdel", action_type="content_delete", tenant_id=tenant.id, gloc=gloc, user_id=owner, role=Role.owner, feature="gbp_posts",
                                           content={"post": name}, label="Google Post deletion", send=remove, verify=gone, provider=provider)
                ok2 = out2["outcome"] == "done" and out2.get("verified") is True
                rep.add("post: delete through the engine, Google must no longer list it", PASS if ok2 else FAIL, f"action {out2.get('action_id')}; {out2.get('detail') or ''}", verified=ok2)
        db.commit()
    finally:
        db.close()
    print("\nRESULT: " + ("all executed steps passed through the governed path AND were read back from Google" if not rep.failed else f"{rep.failed} step(s) FAILED; see above") + ("  [MOCKED: not evidence about Google]" if mocked else ""))
    path = getattr(args, "report", None)
    if path:
        import json

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep.as_dict(), fh, indent=2)
        print(f"Report written to {path}")
    return 1 if rep.failed else 0


def add_commands(sub) -> None:
    p = sub.add_parser("preflight", help="check the real configuration before going live")
    p.add_argument("--smtp-test", metavar="EMAIL", help="send one real test email to this address")
    p.add_argument("--sentry-test", action="store_true", help="send one test event to Sentry")
    a = sub.add_parser("set-admin-password", help="set a new platform-admin password and sign that account out")
    a.add_argument("--email", required=True)
    w = sub.add_parser("google-write-test", help="controlled LIVE write test on a test location (dry run unless --execute)")
    w.add_argument("--connection", help="google_connections.id")
    w.add_argument("--location", required=True, help="locations/<id> of a throwaway/test location")
    w.add_argument("--post", action="store_true")
    w.add_argument("--photo", action="store_true")
    w.add_argument("--reply-review", metavar="REVIEW_ID")
    w.add_argument("--reply-text")
    w.add_argument("--profile", action="store_true", help="change the description, read it back, restore it, read that back")
    w.add_argument("--keep-reply", action="store_true", help="leave the test reply published (default: delete it and confirm it is gone)")
    w.add_argument("--execute", action="store_true", help="really send to Google")
    w.add_argument("--confirm-location", help="repeat --location to confirm")
    w.add_argument("--confirm-title", help="the profile's real title exactly as Google returns it (printed before anything is sent)")
    w.add_argument("--report", metavar="FILE.json", help="write the step-by-step result, with which steps were read back from Google")
    t = sub.add_parser("autonomy-live-test", help="controlled LIVE test of the GOVERNED path (policy, approval, read-back, history) on a test location (dry run unless --execute)")
    t.add_argument("--connection", help="google_connections.id")
    t.add_argument("--location", required=True, help="locations/<id> of a throwaway/test location")
    t.add_argument("--profile", action="store_true")
    t.add_argument("--post", action="store_true")
    t.add_argument("--execute", action="store_true", help="really send to Google")
    t.add_argument("--confirm-location", help="repeat --location to confirm")
    t.add_argument("--confirm-title", help="the profile's real title exactly as Google returns it (printed before anything is sent)")
    t.add_argument("--report", metavar="FILE.json", help="write the step-by-step result")


def run(args: argparse.Namespace) -> int:
    return {"preflight": preflight, "set-admin-password": set_admin_password, "google-write-test": google_write_test, "autonomy-live-test": autonomy_live_test}[args.cmd](args)
