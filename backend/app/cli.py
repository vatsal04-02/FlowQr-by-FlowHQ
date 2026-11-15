"""Operator CLI.   python -m app.cli card-url-audit [--live]
                   python -m app.cli google-smoke [--connection ID] [--location locations/N] [--validate-patch]

Going live: `preflight`, `set-admin-password`, `google-write-test` (see app/ops_cli.py).
`card-url-audit` MUST pass before generating physical cards: the URL is printed/encoded permanently.
`google-smoke` is a READ-ONLY live check of the Google Business Profile integration (services/google/smoke.py).
"""
import argparse
import secrets
import sys

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


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("card-url-audit", help="verify the permanent card URL configuration before printing cards")
    a.add_argument("--live", action="store_true", help="probe the real domain over HTTPS")
    a.add_argument("--expect-domain", help="e.g. go.flowqr.co.in")
    from app.services.google import smoke

    g = sub.add_parser("google-smoke", help="read-only live check of the Google Business Profile integration")
    smoke.add_arguments(g)
    from app import ops_cli

    ops_cli.add_commands(sub)
    from app.ai_eval import cli as ai_eval_cli

    ai_eval_cli.add_commands(sub)
    args = ap.parse_args()
    if args.cmd in ("ai-eval", "ai-eval-human", "ai-eval-rescore"):
        sys.exit(ai_eval_cli.run(args))
    if args.cmd in ("preflight", "set-admin-password", "google-write-test", "autonomy-live-test"):
        sys.exit(ops_cli.run(args))
    sys.exit(smoke.run(args) if args.cmd == "google-smoke" else card_url_audit(args.live, args.expect_domain))


if __name__ == "__main__":
    main()
