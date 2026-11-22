"""Launcher for the controlled worker/beat/API run (audit Journeys 2 and 8; see README.md). ONLY the Google provider is replaced (a file-driven fake, never real Google); the API, Celery worker,
Celery beat, Redis broker and PostgreSQL are the real code. Usage: python mockgoogle.py api|worker|beat
Environment: FLOWQR_BACKEND (path of the backend folder), FAKE_GOOGLE_CONTROL (the JSON file that scripts what the fake returns), API_PORT (default 8700), plus the app's own settings
(DATABASE_URL, REDIS_URL, ...). Needs a LOCAL, DISPOSABLE database: it must never be pointed at production."""
import json
import os
import sys

BACKEND = os.environ.get("FLOWQR_BACKEND") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
CONTROL = os.environ.get("FAKE_GOOGLE_CONTROL") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_google.json")

from app.services import google as g  # noqa: E402
from app.services.google.provider import GAccount, GLocation, GReview, GReviewPage, TokenSet  # noqa: E402


def control() -> dict:
    try:
        return json.load(open(CONTROL, encoding="utf8"))
    except (OSError, ValueError):
        return {}


class FileFake:
    """TEST DOUBLE driven by fake_google.json: per-business review lists (by the token's tag), pages of 2, and injectable failures."""

    def build_auth_url(self, state): return f"https://accounts.google.test/auth?state={state}"
    def exchange_code(self, code): return TokenSet(f"AT-{code}", 3600, f"RT-{code}", "openid email https://www.googleapis.com/auth/business.manage")
    def refresh_access_token(self, rt): return TokenSet("AT-" + rt.removeprefix("RT-"), 3600)
    def get_userinfo(self, at): return {"sub": "sub-" + at.removeprefix("AT-"), "email": f"{at.removeprefix('AT-')}@clinic.example.com"}
    def list_accounts(self, at): return [GAccount("accounts/111", "Clinic")]
    def list_locations(self, at, acct): return [GLocation(acct, "locations/222", "Clinic Gomti Nagar", "Lucknow", "PID1", "https://g.page/r/FAKE/review")]
    def revoke(self, token): pass

    def list_reviews(self, at, acct, loc, page_token=None):
        tag = at.removeprefix("AT-")
        c = control().get(tag, {})
        if c.get("mode") == "rate_limited":
            raise g.GoogleRateLimited(120)
        if c.get("mode") == "server_error":
            raise g.GoogleAPIError(503, "backend unavailable")
        if c.get("mode") == "revoked":
            raise g.GoogleAuthRevoked("revoked")
        from datetime import datetime

        def newest_first(r):  # Google lists reviews by updateTime DESC, and the sync stops early relying on that. An unparseable timestamp sorts first (it is the poison case).
            try:
                return -datetime.fromisoformat((r.get("updated") or r["created"]).replace("Z", "+00:00")).timestamp()
            except ValueError:
                return float("-inf")
        rows = sorted(c.get("reviews", []), key=newest_first)
        start = int(page_token or 0)
        page = rows[start:start + 2]  # two per page, so pagination is exercised
        nxt = str(start + 2) if start + 2 < len(rows) else None
        # a duplicate of the last row of the previous page, as Google can repeat an item across pages
        if start and rows:
            page = [rows[start - 1]] + page
        return GReviewPage(reviews=[GReview(external_id=r["id"], rating=r["rating"], text=r.get("text"), reviewer_name=r.get("name", "Reviewer"), created_at=r["created"],
                                            updated_at=r.get("updated", r["created"]), reply_text=r.get("reply")) for r in page], next_page_token=nxt)


g.get_google_provider = lambda: FileFake()

if __name__ == "__main__":
    role = sys.argv[1]
    if role == "api":
        import uvicorn
        from app.main import app
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("API_PORT", "8700")), proxy_headers=True)
    elif role == "worker":
        from app.workers.celery_app import celery_app
        celery_app.worker_main(["worker", "--pool=solo", "-l", "INFO", "--without-gossip", "--without-mingle"])
    elif role == "beat":
        from app.workers.celery_app import celery_app
        celery_app.start(argv=["beat", "-l", "INFO"])
