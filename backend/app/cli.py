"""Operator CLI.   python -m app.cli card-url-audit [--live]
                   python -m app.cli google-smoke [--connection ID] [--location locations/N] [--validate-patch]

Going live: `preflight`, `set-admin-password`, `google-write-test` (see app/ops_cli.py).
`card-url-audit` MUST pass before generating physical cards: the URL is printed/encoded permanently.
`google-smoke` is a READ-ONLY live check of the Google Business Profile integration (services/google/smoke.py).
"""
import argparse
import secrets
import sys
import uuid

import httpx
from sqlalchemy import func, select

from app.core.config import _bad_host, settings
from app.core.db import system_session
from app.models import CardBatch, QRCard
from app.services.qr import card_nfc_url, card_url, qr_png

OK, FAIL, WARN = "PASS", "FAIL", "WARN"


def card_url_audit(live: bool, expect_domain: str | None) -> int:
    results: list[tuple[str, str, str]] = []

    def check(status: str, name: str, detail: str = "") -> None:
        results.append((status, name, detail))

    base = settings.public_card_base_url.rstrip("/")
    sample = card_url("SAMPLE_TOKEN_0123456789ab")

    why = _bad_host(base)
    check(FAIL if why else OK, "base URL is a public https domain", why or base)
    if settings.app_env in ("development", "test"):
        check(WARN, f"APP_ENV={settings.app_env}", "audit is only meaningful with APP_ENV=staging|production")
    if expect_domain:
        check(OK if base == f"https://{expect_domain}" else FAIL, "base URL equals the expected card domain", f"{base} vs https://{expect_domain}")
    from urllib.parse import urlparse
    u = urlparse(base)
    check(OK if u.path in ("", "/") and not u.query and not u.fragment else FAIL, "base URL has no path/query", base)
    check(OK if sample == f"{base}/c/SAMPLE_TOKEN_0123456789ab" else FAIL, "card URL shape is {base}/c/{token}", sample)
    check(OK if card_url("SAMPLE_TOKEN_0123456789ab", "q") == f"{base}/q/SAMPLE_TOKEN_0123456789ab" else FAIL, "printed QR address shape is {base}/q/{token}", card_url("SAMPLE_TOKEN_0123456789ab", "q"))
    check(OK if card_nfc_url("SAMPLE_TOKEN_0123456789ab") == f"{base}/n/SAMPLE_TOKEN_0123456789ab" else FAIL, "NFC address shape is {base}/n/{token}", card_nfc_url("SAMPLE_TOKEN_0123456789ab"))

    # QR encodes exactly the URL (decode if OpenCV is available)
    try:
        import cv2, numpy as np  # noqa: E401

        img = cv2.imdecode(np.frombuffer(qr_png(sample), np.uint8), cv2.IMREAD_COLOR)
        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        check(OK if decoded == sample else FAIL, "QR decodes to the card URL", decoded)
    except ImportError:
        check(WARN, "QR decode check skipped", "opencv not installed in this image (covered by the test-suite)")

    db = system_session()
    try:
        batches = db.scalars(select(CardBatch)).all()
        legacy = [b for b in batches if not b.base_url]
        mismatched = [b for b in batches if b.base_url and b.base_url != base]
        total = db.scalar(select(func.count()).select_from(QRCard)) or 0
        check(OK if not mismatched else FAIL, "existing batches were generated with the current base URL",
              ", ".join(f"{b.name}: {b.base_url}" for b in mismatched) or f"{len(batches)} batch(es), {total} card(s)")
        if legacy:
            check(WARN, "batches without a recorded base URL (created before auditing existed)", ", ".join(b.name for b in legacy))
        tokens = db.scalars(select(QRCard.public_token)).all()
        check(OK if all(len(t) >= 24 for t in tokens) and len(set(tokens)) == len(tokens) else FAIL, "all card tokens unique and >= 24 chars", str(len(tokens)))
    finally:
        db.close()

    if live:
        probe = secrets.token_urlsafe(18)
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as c:  # default TLS verification: a bad certificate FAILS the audit
                page = c.get(f"{base}/c/{probe}")
                check(OK if page.status_code == 200 and "text/html" in page.headers.get("content-type", "") else FAIL, "GET /c/{token} serves the landing page over valid TLS", f"HTTP {page.status_code}")
                for door in ("q", "n"):
                    page_q = c.get(f"{base}/{door}/{probe}")
                    check(OK if page_q.status_code == 200 and "text/html" in page_q.headers.get("content-type", "") else FAIL, f"GET /{door}/{{token}} serves the landing page over valid TLS", f"HTTP {page_q.status_code}")
                api = c.get(f"{base}/api/v1/public/c/{probe}")
                check(OK if api.status_code == 404 and api.json().get("detail", {}).get("state") == "not_found" else FAIL, "card API reachable on the card domain (unknown token -> not_found)", f"HTTP {api.status_code}")
                other = c.get(f"{base}/dashboard")
                check(OK if other.status_code in (301, 302, 307, 308) else FAIL, "non-card paths on the card domain redirect away", f"HTTP {other.status_code}")
                if base.startswith("https://"):
                    plain = c.get("http://" + base[len("https://"):] + f"/c/{probe}")
                    check(OK if plain.status_code in (301, 308) and str(plain.headers.get("location", "")).startswith("https://") else FAIL, "http:// upgrades to https://", f"HTTP {plain.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            check(FAIL, "live probe", f"{type(exc).__name__}: {exc}")
    else:
        check(WARN, "live probe skipped", "re-run with --live from a host that can reach the card domain")

    width = max(len(n) for _, n, _ in results)
    for st, n, d in results:
        print(f"[{st}] {n.ljust(width)}  {d}")
    failed = [r for r in results if r[0] == FAIL]
    print(f"\n{'AUDIT FAILED' if failed else 'AUDIT PASSED'}: {len(failed)} failure(s), {sum(1 for r in results if r[0] == WARN)} warning(s)")
    return 1 if failed else 0


def _agency_cli(args) -> int:
    """Agency account set-up. `register` is the only command that talks to Google (one code exchange, started by a person). Nothing here prints a token."""
    from app.services import google as gg
    from app.services.google import agency
    from app.services.google import agency_client as ac

    if args.cmd == "google-agency-auth-url":
        if not settings.google_configured:
            print("FAIL: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not configured")
            return 1
        if not settings.agency_token_encryption_key:
            print("FAIL: AGENCY_TOKEN_ENCRYPTION_KEY is not set (the sign-in state is signed with it)")
            return 1
        print("Sign in to the AGENCY Google account (not a person's own account) and open:")
        print(agency.agency_auth_url(gg.get_google_provider(), agency.new_oauth_state()))
        print()
        print(f"After you approve, Google sends the browser to {settings.google_redirect_uri}")
        print("The app's callback rejects this sign-in on purpose (invalid_state, the code is NOT used) and then sends the browser on to another page, so the code stays in the address bar only if nothing")
        print("is listening at that address (stop the local frontend first). Otherwise copy the callback request's URL from the browser's developer tools (Network, Preserve log).")
        print("Easier and more reliable: run google-agency-register --listen instead, which receives this redirect itself and needs no copying.")
        print("Take BOTH the `code=` and the `state=` values from that address (turn %2F into /) and run google-agency-register with the SAME GOOGLE_REDIRECT_URI.")
        print("The code is single-use and expires within minutes; the state is single-use and expires after 15 minutes. Neither is a long-lived secret, but do not share them.")
        return 0
    if args.cmd == "google-agency-register":
        if not settings.agency_token_encryption_key:
            print("FAIL: AGENCY_TOKEN_ENCRYPTION_KEY is not set (generate one with Fernet.generate_key(); it must differ from TOKEN_ENCRYPTION_KEY)")
            return 1
        if settings.agency_token_encryption_key in (settings.token_encryption_key, settings.secret_key):
            print("FAIL: AGENCY_TOKEN_ENCRYPTION_KEY must differ from TOKEN_ENCRYPTION_KEY and SECRET_KEY")
            return 1
        shown_group = args.location_group_id or settings.google_agency_location_group_id
        if shown_group and ac.looks_like_account_number(shown_group):
            print(f"WARNING: {shown_group} looks like an accountNumber (a short display reference), not an API resource name. The API names the group accounts/<long id>, as accounts.list returns it. "
                  "Registering still works, but the group will not be found until it is corrected: run google-agency-check to see the resource names this login can list.")
        code, state = args.code, args.state
        if getattr(args, "listen", False):
            from app.services.google import agency_listen

            try:
                _host, port, path = agency_listen.parse_redirect(settings.google_redirect_uri)
                server = agency_listen.open_listener(args.listen_host, port)  # bound BEFORE the address is shown: a busy port is found now, not after you have signed in
                state = agency.new_oauth_state()
                print(f"Listening on port {port} for Google's redirect. Open this address in a private window, signed in as {args.expect_email} ONLY, and approve:")
                print(agency.agency_auth_url(gg.get_google_provider(), state))
                print(f"\nWaiting up to {args.listen_timeout} seconds. Nothing needs to be copied: this command receives the redirect itself.", flush=True)
                code, err = agency_listen.wait_for_callback(server, path=path, expected_state=state, timeout=args.listen_timeout)
            except (agency_listen.ListenError, agency.AgencyError) as exc:
                print(f"FAIL: {exc}")
                return 1
            if err or not code:
                print(f"FAIL: Google did not complete the sign-in ({err or 'no code'}). Nothing was stored.")
                return 1
            print("Received the sign-in. Checking it and registering...", flush=True)
        elif not (code and state):
            print("FAIL: give both --code and --state (from the redirect), or use --listen so this command receives the redirect itself")
            return 1
        try:
            account_id = agency.register_account(args.label, code=code, max_locations=args.max_locations, location_group_id=args.location_group_id, expected_email=args.expect_email, state=state)
        except (agency.AgencyError, gg.GoogleError) as exc:
            print(f"FAIL: {type(exc).__name__}: {str(exc)[:160]}")
            return 1
        print(f"PASS: agency account '{args.label}' stored ({account_id}). Re-run google-agency-status to see it.")
        return 0
    if args.cmd == "google-agency-check":
        from app.services.google import agency_check

        if not settings.agency_token_encryption_key:
            print("FAIL: AGENCY_TOKEN_ENCRYPTION_KEY is not set")
            return 1
        checks = agency_check.run_checks(account=args.account, expected_email=args.expect_email, locations=args.location or [], connection_id=args.connection_id, group=args.location_group_id, title=getattr(args, "title", None))
        width = max(len(c.name) for c in checks)
        for c in checks:
            print(f"[{c.status}] {c.name.ljust(width)}  {c.detail}")
        good = agency_check.ok(checks)
        print("\nREAD-ONLY CHECK " + ("PASSED: the agency login reads the location through the group." if good else "DID NOT PASS: see the FAIL/SKIP lines above. Nothing was written to Google or to the database."))
        return 0 if good else 1
    if args.cmd == "google-agency-rollback":
        from app.models import GoogleConnection

        db = system_session()
        try:
            conn = db.get(GoogleConnection, args.connection_id)
            if conn is None:
                print("FAIL: no such connection")
                return 1
            try:
                agency.rollback_to_client_token(db, conn)
            except (agency.AgencyError, gg.GoogleError) as exc:
                print(f"FAIL: {str(exc)[:200]}")
                return 1
            print("PASS: the connection uses the client's own Google login again. FlowQR's group may still be a manager in Google until it is removed there.")
            return 0
        finally:
            db.close()
    from app.models import GoogleAgencyAccount, GoogleAgencyAuthorization

    db = system_session()
    try:
        rows = db.scalars(select(GoogleAgencyAccount).order_by(GoogleAgencyAccount.created_at)).all()
        if not rows:
            print("No agency accounts registered.")
        for a in rows:
            n = db.scalar(select(func.count(func.distinct(GoogleAgencyAuthorization.google_location_id))).where(
                GoogleAgencyAuthorization.agency_account_id == a.id, GoogleAgencyAuthorization.status.in_(agency.LIVE))) or 0
            suspicious = " (WARNING: looks like an accountNumber, not an API resource name: run google-agency-check)" if a.location_group_name and ac.looks_like_account_number(a.location_group_name) else ""
            print(f"{a.label}	{a.google_email}	{a.status}	group: {(a.location_group_name or 'none (individual fallback only)') + suspicious}	live locations: {n}	cap: {a.max_locations or settings.google_agency_max_locations_per_account or 'unknown (not verified)'}")
    finally:
        db.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("card-url-audit", help="verify the permanent card URL configuration before printing cards")
    a.add_argument("--live", action="store_true", help="probe the real domain over HTTPS")
    a.add_argument("--expect-domain", help="e.g. go.flowqr.co.in")
    from app.services.google import smoke

    g = sub.add_parser("google-smoke", help="read-only live check of the Google Business Profile integration")
    smoke.add_arguments(g)
    from app.services.google import readiness

    r = sub.add_parser("google-readiness", help="Milestone 2: reads and validateOnly patches on ONE designated test profile (never writes)")
    readiness.add_arguments(r)
    sub.add_parser("privacy-retention-report", help="COUNT what the provisional privacy retention job would remove (ended sessions, reset tokens, audit-log IPs, demo leads). Deletes nothing.")
    sub.add_parser("google-retention-report", help="COUNT what the Google-content retention job would expire (reviews, snapshots, metrics, drafts, agent tasks). Changes nothing.")
    sub.add_parser("google-agency-auth-url", help="print the Google sign-in URL a PERSON opens while signed in to a FlowQR AGENCY Google account (the only live step of registering one)")
    ar = sub.add_parser("google-agency-register", help="store an agency Google login from the authorization code that sign-in produced (tokens are encrypted with AGENCY_TOKEN_ENCRYPTION_KEY, never printed)")
    ar.add_argument("--label", required=True, help="a name for this agency account, e.g. agency-1")
    ar.add_argument("--code", help="the single-use authorization code from the redirect (not needed with --listen)")
    ar.add_argument("--listen", action="store_true", help="RECOMMENDED: this command opens a one-shot local listener, shows the sign-in address, and receives the redirect itself: nothing to copy. Needs the redirect port free (stop FlowQR's local frontend)")
    ar.add_argument("--listen-host", default="127.0.0.1", help="the address to bind (default 127.0.0.1; inside Docker use 0.0.0.0 and publish the port to 127.0.0.1 only)")
    ar.add_argument("--listen-timeout", type=int, default=600, help="seconds to wait for the sign-in with --listen (default 600)")
    ar.add_argument("--location-group-id", help="the FlowQR Location Group this Google user belongs to, as its API RESOURCE NAME exactly as accounts.list returns it, e.g. accounts/114863040359228435467. NOT the short accountNumber (e.g. 5488245563) that Business Profile Manager shows (default: GOOGLE_AGENCY_LOCATION_GROUP_ID). Without one the login can only be used for the individual fallback")
    ar.add_argument("--max-locations", type=int, help="only from a written Google answer; leave out while Google's limit is unverified")
    ar.add_argument("--expect-email", required=True, help="the agency Google account you signed in as (e.g. the FlowHQ agency address). Google's own answer must match it or NOTHING is stored and the sign-in is revoked")
    ar.add_argument("--state", help="the `state=` value from the same redirect as the code: it must be one google-agency-auth-url issued, unexpired and not used before (not needed with --listen)")
    ac_ = sub.add_parser("google-agency-check", help="READ-ONLY: with the stored agency token, list the FlowQR LocationGroup and read one client location through it (no writes; other clients are counted, never named)")
    ac_.add_argument("--expect-email", required=True, help="the agency Google account this login must be")
    ac_.add_argument("--account", help="the label or e-mail of the registered agency login (default: the only one)")
    ac_.add_argument("--location", action="append", help="a Google location id to find under the group, e.g. locations/1234567890 (repeatable)")
    ac_.add_argument("--title", help="find the location by (part of) its title, e.g. \"Geeta Krishna\". Exactly one location in the group must match: only that one is named, never the others")
    ac_.add_argument("--connection-id", type=uuid.UUID, help="a FlowQR Google connection whose selected locations are looked for (this database only)")
    ac_.add_argument("--location-group-id", help="override the group (default: the one recorded for the login)")
    rb = sub.add_parser("google-agency-rollback", help="put a connection back on the CLIENT's own Google login while that token is still held (see GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS)")
    rb.add_argument("--connection-id", required=True, type=uuid.UUID, help="the FlowQR Google connection id")
    sub.add_parser("google-agency-status", help="list agency accounts and how many client locations each holds (no tokens)")
    from app import ops_cli

    ops_cli.add_commands(sub)
    from app.ai_eval import cli as ai_eval_cli

    ai_eval_cli.add_commands(sub)
    args = ap.parse_args()
    if args.cmd in ("ai-eval", "ai-eval-human", "ai-eval-rescore", "ai-eval-wa"):
        sys.exit(ai_eval_cli.run(args))
    if args.cmd in ("preflight", "set-admin-password", "google-write-test", "autonomy-live-test", "registration"):
        sys.exit(ops_cli.run(args))
    if args.cmd == "privacy-retention-report":
        from app.core.db import system_session
        from app.services import retention

        db = system_session()
        try:
            out = retention.run(db, dry_run=True)
        finally:
            db.close()
        print(f"DRY RUN: nothing was changed. Would remove: {out['counts']}; errors: {out['errors'] or 'none'}")
        sys.exit(1 if out["errors"] else 0)
    if args.cmd == "google-retention-report":
        from app.core.db import system_session
        from app.services import google_retention

        db = system_session()
        try:
            out = google_retention.run(db, dry_run=True)
        finally:
            db.close()
        print(f"DRY RUN: nothing was changed. Would expire: {out['counts']}; errors: {out['errors'] or 'none'}")
        sys.exit(1 if out["errors"] else 0)
    if args.cmd in ("google-agency-auth-url", "google-agency-register", "google-agency-status", "google-agency-check", "google-agency-rollback"):
        sys.exit(_agency_cli(args))
    if args.cmd == "google-readiness":
        from app.services.google import readiness as _readiness

        sys.exit(_readiness.run(args))
    sys.exit(smoke.run(args) if args.cmd == "google-smoke" else card_url_audit(args.live, args.expect_domain))


if __name__ == "__main__":
    main()
