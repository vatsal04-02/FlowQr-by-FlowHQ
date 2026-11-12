"""Live smoke test for the Google Business Profile integration. READ-ONLY: it never creates, edits or deletes anything.

    python -m app.cli google-smoke --connection <google_connections.id>     # token already stored (encrypted) by a real connect
    GOOGLE_SMOKE_REFRESH_TOKEN=... python -m app.cli google-smoke           # or a refresh token from the environment
    ... [--location locations/123] [--validate-patch]

Each Google call is reported as PASS / FAIL / NOT APPROVED / RATE LIMITED with what Google actually answered. Nothing is
assumed: a call that was not made is reported as SKIPPED, and no token is ever printed.

`--validate-patch` additionally sends the location's *current* description back with `validateOnly=true`, which Google
documents as validation without updating. It is off by default.

Exit code: 0 all calls passed · 1 at least one failed · 2 blocked before any call (no credentials / no token) ·
3 Google has not approved or enabled the API for the project.
"""
import argparse
import os
import uuid
from datetime import date, timedelta

from app.core.config import settings
from app.services import google as g
from app.services.google.provider import INFO_URL, PERFORMANCE_METRICS, has_business_scope


def _line(status: str, name: str, detail: str = "") -> None:
    print(f"  {status:<14} {name:<34} {detail}"[:200])


class Run:
    def __init__(self) -> None:
        self.failed = 0
        self.unapproved = False

    def call(self, name: str, fn, describe=lambda r: ""):
        try:
            result = fn()
        except g.GoogleApiNotApproved as exc:
            self.unapproved = True
            why = "API not enabled on the project" if exc.why == "service_disabled" else "quota 0: access request not approved"
            _line("NOT APPROVED", name, f"HTTP {exc.status} - {why}" + (f" ({exc.service})" if exc.service else ""))
        except g.GoogleRateLimited as exc:
            self.failed += 1
            _line("RATE LIMITED", name, "HTTP 429" + (f" metric={exc.quota_metric}" if exc.quota_metric else "")
                  + " - if EVERY call says this, the project quota is probably 0 (not approved)")
        except g.GoogleAuthRevoked as exc:
            self.failed += 1
            _line("FAIL", name, f"auth: {exc}")
        except g.GoogleAPIError as exc:
            self.failed += 1
            _line("FAIL", name, f"HTTP {exc.status} {exc.google_status or ''} {exc.reason or ''} {exc}")
        else:
            _line("PASS", name, describe(result))
            return result
        return None


def _refresh_token(connection_id: str | None) -> tuple[str | None, str]:
    env = os.environ.get("GOOGLE_SMOKE_REFRESH_TOKEN")
    if env:
        return env, "GOOGLE_SMOKE_REFRESH_TOKEN"
    if not connection_id:
        return None, ""
    from app.core.db import system_session
    from app.core.security import get_cipher
    from app.models import GoogleConnection

    db = system_session()
    try:
        conn = db.get(GoogleConnection, uuid.UUID(connection_id))
        if not conn or not conn.refresh_token_encrypted:
            return None, ""
        return get_cipher().decrypt(conn.refresh_token_encrypted), f"connection {conn.id} ({conn.status.value})"
    finally:
        db.close()


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--connection", help="google_connections.id whose stored refresh token to use")
    ap.add_argument("--location", help="locations/<id> to test (default: the first one Google lists)")
    ap.add_argument("--validate-patch", action="store_true", help="also send a validateOnly=true (non-mutating) location patch")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli google-smoke", description="Read-only live check of the Google Business Profile integration")
    add_arguments(ap)
    return run(ap.parse_args(argv))


def run(args: argparse.Namespace) -> int:

    print("FlowQR -> Google Business Profile live smoke test (read-only)")
    if not settings.google_configured:
        print("BLOCKED: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. No Google call was made.")
        return 2
    try:
        token_value, source = _refresh_token(args.connection)
    except ValueError:
        print("BLOCKED: --connection is not a valid id.")
        return 2
    if not token_value:
        print("BLOCKED: no refresh token. Pass --connection <id> of a connected account or set GOOGLE_SMOKE_REFRESH_TOKEN. No Google call was made.")
        return 2
    print(f"Token source: {source}\n")

    provider = g.get_google_provider()
    run = Run()
    ts = run.call("oauth: refresh access token", lambda: provider.refresh_access_token(token_value),
                  lambda t: f"expires_in={t.expires_in}s scope_ok={has_business_scope(t.scope) if t.scope else 'not returned'}")
    if ts is None:
        print("\nStopped: without an access token nothing else can be tested.")
        return 1
    if ts.scope and not has_business_scope(ts.scope):
        _line("FAIL", "oauth: business.manage scope", "the token does not include it; reconnect and grant Business Profile access")
        return 1
    at = ts.access_token

    accounts = run.call("accounts.list", lambda: provider.list_accounts(at), lambda a: f"{len(a)} account(s)")
    location, account = args.location, None
    if accounts:
        for acct in accounts:
            locs = run.call(f"locations.list {acct.name}", lambda acct=acct: provider.list_locations(at, acct.name), lambda l: f"{len(l)} location(s)")
            for loc in locs or []:
                if account is None and (not location or loc.name == location):
                    account, location = acct.name, loc.name
    if not account or not location:
        _line("SKIPPED", "per-location calls", "no accessible location was found" if not run.unapproved else "project not approved")
    else:
        print(f"\n  Using {account}/{location}")
        end = date.today() - timedelta(days=3)
        start = end - timedelta(days=6)
        run.call("locations.get (readMask)", lambda: provider.get_location_details(at, location), lambda d: f"title={d.get('title')!r} hours={len(d.get('hours') or [])}")
        run.call("categories.list", lambda: provider.search_categories(at, "rest"), lambda c: f"{len(c)} match(es)")
        run.call("reviews.list", lambda: provider.list_reviews(at, account, location), lambda p: f"{len(p.reviews)} on first page, more={bool(p.next_page_token)}")
        run.call("localPosts.list", lambda: provider.list_posts(at, account, location), lambda p: f"{len(p)} post(s)")
        run.call("media.list", lambda: provider.list_media(at, account, location), lambda m: f"{len(m)} item(s)")
        run.call("performance.fetchMultiDaily", lambda: provider.fetch_performance(at, location, start.isoformat(), end.isoformat(), PERFORMANCE_METRICS),
                 lambda s: f"{len(s)}/{len(PERFORMANCE_METRICS)} metrics returned data")
        if args.validate_patch:
            def validate():
                current = provider._send("GET", f"{INFO_URL}/{location}", at, params={"readMask": "profile"})
                if not (current.get("profile") or {}).get("description"):
                    return "skipped: the location has no description to send back"
                provider._send("PATCH", f"{INFO_URL}/{location}", at, params={"updateMask": "profile", "validateOnly": "true"}, json={"profile": current["profile"]})
                return "Google validated the request (nothing was changed)"
            run.call("locations.patch validateOnly", validate, lambda r: r)
        else:
            _line("SKIPPED", "locations.patch validateOnly", "pass --validate-patch to include it")
    _line("SKIPPED", "write calls", "reply/post/photo/profile edits are never made by this command")

    print()
    if run.unapproved:
        print("RESULT: NOT APPROVED - Google is refusing Business Profile calls for this Cloud project. See docs/GOOGLE_SETUP.md.")
        return 3
    if run.failed:
        print(f"RESULT: {run.failed} call(s) failed.")
        return 1
    print("RESULT: every call made succeeded against the live API. Write operations remain untested.")
    return 0

