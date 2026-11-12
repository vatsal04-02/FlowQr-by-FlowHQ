"""Google OAuth, sync and reply workflow. Uses FakeGoogleProvider - a TEST DOUBLE, not a real Google."""
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, select, text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import GoogleConnection, GoogleLocation, Review
from app.services import google as g
from app.services.google.provider import GAccount, GLocation, GReview, GReviewPage, TokenSet
from tests.conftest import make_business, make_user, owner_query


class FakeGoogleProvider:
    """TEST DOUBLE. Implements GoogleBusinessProvider with in-memory data."""

    def __init__(self):
        self.reviews: list[GReview] = []
        self.refresh_calls = 0
        self.fail_refresh_with = None
        self.list_error = None
        self.reply_error = None
        self.replies: list[tuple] = []
        self.revoked = []
        self.list_calls = 0

    def build_auth_url(self, state): return f"https://accounts.google.test/auth?state={state}"
    def exchange_code(self, code): return TokenSet("access-1", 3600, "REFRESH-SECRET-TOKEN", "openid email https://www.googleapis.com/auth/business.manage")
    def refresh_access_token(self, rt):
        self.refresh_calls += 1
        if self.fail_refresh_with:
            raise self.fail_refresh_with
        return TokenSet(f"access-r{self.refresh_calls}", 3600)
    def get_userinfo(self, at): return {"sub": "g-sub-1", "email": "owner@clinic.example.com"}
    def list_accounts(self, at): return [GAccount("accounts/111", "Clinic")]
    def list_locations(self, at, acct):
        return [GLocation(acct, "locations/222", "Clinic Gomti Nagar", "Gomti Nagar, Lucknow", "PID1", "https://g.page/r/FAKE/review"),
                GLocation(acct, "locations/333", "Clinic Aliganj", "Aliganj, Lucknow", "PID2", None)]
    def list_reviews(self, at, acct, loc, page_token=None):
        self.list_calls += 1
        if self.list_error:
            raise self.list_error
        return GReviewPage(reviews=list(self.reviews))
    def reply_to_review(self, at, acct, loc, review_id, comment):
        if self.reply_error:
            raise self.reply_error
        self.replies.append((review_id, comment))
    def revoke(self, token): self.revoked.append(token)


def greview(i, rating=5, text="Great clinic", reply=None, updated="2025-01-02T10:00:00Z"):
    return GReview(external_id=f"rev-{i}", rating=rating, text=text, reviewer_name=f"Reviewer {i}",
                   created_at="2025-01-01T10:00:00Z", updated_at=updated, reply_text=reply)


@pytest.fixture()
def fake(monkeypatch):
    f = FakeGoogleProvider()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


def connect(biz, fake, client_cookies=True):
    """Drive the full OAuth round-trip against the fake provider."""
    r = biz.post("/google/connect")
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["auth_url"]).query)["state"][0]
    return state


def callback(biz, state, code="auth-code", **kw):
    return biz.http.get("/api/v1/google/callback", params={"code": code, "state": state, **kw}, follow_redirects=False)


@pytest.fixture()
def connected(fake):
    biz = make_business("Gomti Physio")
    state = connect(biz, fake)
    r = callback(biz, state)
    assert r.status_code == 303 and "connected=1" in r.headers["location"], r.headers["location"]
    status = biz.get("/google/status").json()
    biz.conn_id = status["connections"][0]["id"]
    biz.glocs = biz.get(f"/google/connections/{biz.conn_id}/locations").json()
    return biz


def sync_select(biz, fake):
    sel = [{"google_location_id": biz.glocs[0]["id"], "selected": True, "location_id": biz.location_id}]
    r = biz.http.put(f"/api/v1/google/connections/{biz.conn_id}/selection", json={"selections": sel}, headers={"X-CSRF-Token": biz.csrf})
    assert r.status_code == 200, r.text
    return r.json()


def test_config_pending_state_is_honest(monkeypatch):
    biz = make_business("Pending Co")
    monkeypatch.setattr(settings, "google_client_id", "")
    s = biz.get("/google/status").json()
    assert s["configured"] is False and "not configured" in s["configuration_note"].lower()
    r = biz.post("/google/connect")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "google_config_pending"


def test_connect_requires_admin(fake, biz_a):
    staff = make_user()  # not a member of anything
    assert staff.post("/google/connect").status_code in (401, 403)


def test_oauth_callback_rejects_bad_state_and_mismatched_nonce(fake):
    biz = make_business("State Co")
    state = connect(biz, fake)
    # tampered state
    r = callback(biz, state[:-3] + "abc")
    assert "error=invalid_state" in r.headers["location"]
    # attacker replays a valid state in a browser lacking the nonce cookie (e.g. victim of CSRF)
    biz.http.cookies.delete("flowqr_oauth_state")
    r = callback(biz, state)
    assert "error=invalid_state" in r.headers["location"]
    # user denied consent
    assert "error=access_denied" in callback(biz, state, error="access_denied").headers["location"]
    assert biz.get("/google/status").json()["connections"] == []


def test_callback_for_other_users_state_is_rejected(fake):
    victim, attacker = make_business("Victim"), make_business("Attacker")
    state = connect(victim, fake)
    # attacker's browser tries to finish the victim's flow
    attacker.http.cookies.set("flowqr_oauth_state", victim.http.cookies.get("flowqr_oauth_state"))
    r = callback(attacker, state)
    assert "error=session_mismatch" in r.headers["location"]


def test_refresh_token_encrypted_at_rest_and_never_returned(connected, fake):
    enc = owner_query("SELECT refresh_token_encrypted FROM google_connections WHERE id=:i", i=connected.conn_id)[0][0]
    assert enc and "REFRESH-SECRET-TOKEN" not in enc
    from app.core.security import get_cipher
    assert get_cipher().decrypt(enc) == "REFRESH-SECRET-TOKEN"
    for path in ["/google/status", f"/google/connections/{connected.conn_id}/locations", "/auth/me"]:
        body = connected.get(path).text
        assert "REFRESH-SECRET" not in body and "refresh_token" not in body and "access-1" not in body
    assert len(connected.glocs) == 2 and connected.get("/google/status").json()["connections"][0]["status"] == "pending_selection"


def test_selection_sync_dedup_and_update_tracking(connected, fake):
    fake.reviews = [greview(1), greview(2, rating=2, text="Long wait"), greview(3, rating=4, text=None)]
    sel = sync_select(connected, fake)
    assert sel[0]["last_sync_status"] == "ok" or any(s["last_sync_status"] == "ok" for s in sel)
    revs = connected.get("/reviews").json()
    assert revs["total"] == 3
    # second sync: no duplicates
    assert connected.post("/google/sync").status_code == 200
    assert connected.get("/reviews").json()["total"] == 3
    # Google edits a review -> tracked as update, not duplicate
    fake.reviews[1] = greview(2, rating=3, text="Long wait but good doctor", updated="2025-02-01T00:00:00Z")
    connected.post("/google/sync")
    revs = connected.get("/reviews").json()
    assert revs["total"] == 3
    edited = next(r for r in revs["items"] if r["text"] == "Long wait but good doctor")
    assert edited["rating"] == 3 and edited["update_count"] == 1
    assert connected.get("/google/connections/%s/locations" % connected.conn_id).json()[0]["last_synced_at"]


def test_review_filters(connected, fake):
    fake.reviews = [greview(1, 5), greview(2, 1, "Rude staff, overcharged"), greview(3, 4, "Nice", reply="Thanks!")]
    sync_select(connected, fake)
    assert connected.get("/reviews", params={"rating": 1}).json()["total"] == 1
    assert connected.get("/reviews", params={"reply_state": "published"}).json()["total"] == 1
    assert connected.get("/reviews", params={"reply_state": "none"}).json()["total"] == 2
    assert connected.get("/reviews", params={"search": "overcharged"}).json()["total"] == 1
    assert connected.get("/reviews", params={"location_id": connected.location_id}).json()["total"] == 3
    flagged = connected.get("/reviews", params={"rating": 1}).json()["items"][0]
    assert "accusation" in flagged["sensitive_reasons"]


def test_rate_limit_and_revocation_handling(connected, fake, monkeypatch):
    sync_select(connected, fake)
    monkeypatch.setattr("app.services.google.sync.time.sleep", lambda s: None)
    fake.list_error = g.GoogleRateLimited(retry_after=1)
    connected.post("/google/sync")
    gl = connected.get(f"/google/connections/{connected.conn_id}/locations").json()[0]
    assert gl["last_sync_status"] == "rate_limited"
    # revoked authorization: refresh fails with invalid_grant
    fake.list_error = None
    from app.models import GoogleConnection
    db = SessionLocal(); set_rls_context(db, bypass=True)
    conn = db.get(GoogleConnection, __import__("uuid").UUID(connected.conn_id))
    conn.access_token_expires_at = None  # force refresh
    gloc = db.scalar(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id, GoogleLocation.selected.is_(True)))
    gloc.next_sync_after = None
    db.commit(); db.close()
    fake.fail_refresh_with = g.GoogleAuthRevoked("revoked")
    connected.post("/google/sync")
    st = connected.get("/google/status").json()["connections"][0]
    assert st["status"] == "revoked" and "reconnect" in st["last_error"].lower()


def test_transient_errors_are_retried_with_backoff(connected, fake, monkeypatch):
    sync_select(connected, fake)
    sleeps = []
    monkeypatch.setattr("app.services.google.sync.time.sleep", sleeps.append)
    calls = {"n": 0}
    orig = fake.list_reviews

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise g.GoogleAPIError(503, "unavailable")
        return orig(*a, **k)
    fake.list_reviews = flaky
    fake.reviews = [greview(9)]
    connected.post("/google/sync")
    assert sleeps == [1, 2] and connected.get("/reviews").json()["total"] == 1


def test_disconnect_wipes_tokens_and_stops_sync(connected, fake):
    sync_select(connected, fake)
    assert connected.delete(f"/google/connections/{connected.conn_id}").status_code == 204
    assert fake.revoked == ["REFRESH-SECRET-TOKEN"]
    row = owner_query("SELECT refresh_token_encrypted, access_token_encrypted, status FROM google_connections WHERE id=:i", i=connected.conn_id)[0]
    assert row[0] is None and row[1] is None and row[2] == "disconnected"
    assert connected.post("/google/sync").status_code == 409


def test_cross_tenant_google_and_review_isolation(connected, fake, biz_b):
    fake.reviews = [greview(1, 1, "Terrible")]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    assert biz_b.get("/reviews").json()["total"] == 0
    assert biz_b.get(f"/reviews/{rid}").status_code == 404
    assert biz_b.post(f"/reviews/{rid}/drafts", json={"body": "hello there"}).status_code == 404
    assert biz_b.get(f"/google/connections/{connected.conn_id}/locations").status_code == 404
    assert biz_b.delete(f"/google/connections/{connected.conn_id}").status_code == 404
    assert biz_b.get("/google/status").json()["connections"] == []
    r = biz_b.http.put(f"/api/v1/google/connections/{connected.conn_id}/selection",
                       json={"selections": [{"google_location_id": connected.glocs[0]["id"], "location_id": biz_b.location_id}]},
                       headers={"X-CSRF-Token": biz_b.csrf})
    assert r.status_code == 404
    # draft ids from tenant A are inaccessible to B
    d = connected.post(f"/reviews/{rid}/drafts", json={"body": "Sorry to hear that."}).json()
    assert biz_b.patch(f"/reply-drafts/{d['id']}", json={"body": "hijack"}).status_code == 404
    assert biz_b.post(f"/reply-drafts/{d['id']}/approve", json={}).status_code == 404
    assert biz_b.post(f"/reply-drafts/{d['id']}/publish").status_code == 404


class StubReplyAI:
    """TEST DOUBLE LLM."""
    name, model = "test-stub", "stub-1"
    def generate(self, system, user, *, max_tokens=600, temperature=0.4):
        return "Thank you for your feedback. We'd love to hear more; please contact us directly."


def test_reply_workflow_requires_human_approval_and_confirms_with_google(connected, fake, monkeypatch):
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: StubReplyAI())
    fake.reviews = [greview(1, 1, "They did the wrong surgery. I will go to court!")]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]

    d = connected.post(f"/reviews/{rid}/drafts/generate")
    assert d.status_code == 201, d.text
    d = d.json()
    assert d["status"] == "draft" and d["generated_by_ai"] and d["requires_human_handling"]
    assert {"medical", "legal"} <= set(d["flag_reasons"]) and d["flag_messages"]
    # cannot publish without approval
    assert connected.post(f"/reply-drafts/{d['id']}/publish").status_code == 409
    # flagged => approval needs explicit acknowledgement
    r = connected.post(f"/reply-drafts/{d['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "flags_need_acknowledgement"
    assert connected.post(f"/reply-drafts/{d['id']}/approve", json={"acknowledge_flags": True}).json()["status"] == "approved"
    # editing voids approval
    edited = connected.patch(f"/reply-drafts/{d['id']}", json={"body": "We are sorry to hear this. Please call us."}).json()
    assert edited["status"] == "draft"
    assert connected.post(f"/reply-drafts/{d['id']}/publish").status_code == 409
    connected.post(f"/reply-drafts/{d['id']}/approve", json={"acknowledge_flags": True})

    # Google failure => failed, NOT published
    fake.reply_error = g.GoogleAPIError(500, "boom")
    r = connected.post(f"/reply-drafts/{d['id']}/publish").json()
    assert r["status"] == "failed" and r["failure_reason"] and r["published_at"] is None
    assert connected.get("/reviews", params={"reply_state": "failed"}).json()["total"] == 1
    assert connected.get(f"/reviews/{rid}").json()["review"]["google_reply_text"] is None
    # retry succeeds => published only now
    fake.reply_error = None
    r = connected.post(f"/reply-drafts/{d['id']}/publish").json()
    assert r["status"] == "published" and r["attempts"] == 2
    assert fake.replies == [("rev-1", "We are sorry to hear this. Please call us.")]
    detail = connected.get(f"/reviews/{rid}").json()
    assert detail["review"]["reply_state"] == "published" and len(detail["logs"]) == 2
    assert [l["success"] for l in reversed(detail["logs"])] == [False, True]


def test_staff_can_draft_but_not_approve_or_publish(connected, fake, monkeypatch):
    fake.reviews = [greview(1)]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    staff = make_user()
    from app.core.db import SessionLocal, set_rls_context
    from app.models import Membership, Role, User
    db = SessionLocal(); set_rls_context(db, bypass=True)
    uid = db.scalar(select(User.id).where(User.email == staff.email))
    db.add(Membership(tenant_id=__import__("uuid").UUID(connected.tenant_id), user_id=uid, role=Role.staff))
    db.commit(); db.close()
    h = {"X-Tenant-Id": connected.tenant_id}
    d = staff.post(f"/reviews/{rid}/drafts", json={"body": "Thanks for visiting us!"}, headers=h)
    assert d.status_code == 201
    did = d.json()["id"]
    assert staff.post(f"/reply-drafts/{did}/approve", json={}, headers=h).status_code == 403
    assert staff.post(f"/reply-drafts/{did}/publish", headers=h).status_code == 403
    assert staff.post("/google/connect", headers=h).status_code == 403


def test_connect_with_unapproved_project_surfaces_awaiting_approval_then_recovers(fake):
    biz = make_business("Awaiting Co")
    fake.list_accounts = lambda at: (_ for _ in ()).throw(g.GoogleApiNotApproved(429, "quota 0"))
    r = callback(biz, connect(biz, fake))
    assert r.status_code == 303 and "connected=1" in r.headers["location"]  # OAuth itself succeeded
    c = biz.get("/google/status").json()["connections"][0]
    assert c["api_access"] == "awaiting_approval" and c["status"] == "error" and "not yet approved" in c["last_error"]
    # Google approves the project: refresh succeeds and the connection recovers
    del fake.list_accounts
    r = biz.post(f"/google/connections/{c['id']}/refresh-locations")
    assert r.status_code == 200 and len(r.json()) == 2
    c = biz.get("/google/status").json()["connections"][0]
    assert c["api_access"] == "approved" and c["status"] == "pending_selection" and c["last_error"] is None


def test_sync_reports_awaiting_approval_and_backs_off(connected, fake):
    sync_select(connected, fake)
    fake.list_error = g.GoogleApiNotApproved(429, "quota 0")
    gl = connected.get(f"/google/connections/{connected.conn_id}/locations").json()[0]
    connected.post("/google/sync")
    gl = connected.get(f"/google/connections/{connected.conn_id}/locations").json()[0]
    assert gl["last_sync_status"] == "awaiting_approval"


def test_connect_without_the_business_scope_is_refused_and_the_token_revoked(fake):
    biz = make_business("Unticked Co")
    fake.exchange_code = lambda code: TokenSet("access-1", 3600, "REFRESH-X", "openid email")  # user unticked Business Profile
    r = callback(biz, connect(biz, fake))
    assert r.status_code == 303 and "error=scope_missing" in r.headers["location"]
    assert biz.get("/google/status").json()["connections"] == [] and fake.revoked == ["REFRESH-X"]


def test_first_contact_quota_error_is_reported_as_probably_unapproved_not_as_a_generic_failure(fake):
    biz = make_business("First Contact Co")
    fake.list_accounts = lambda at: (_ for _ in ()).throw(g.GoogleRateLimited(None))
    callback(biz, connect(biz, fake))
    c = biz.get("/google/status").json()["connections"][0]
    assert c["api_access"] == "awaiting_approval" and "most likely awaiting" in c["last_error"]
    r = biz.post(f"/google/connections/{c['id']}/refresh-locations")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_api_awaiting_approval"


def test_a_rate_limit_on_an_approved_connection_stays_a_rate_limit(connected, fake):
    fake.list_accounts = lambda at: (_ for _ in ()).throw(g.GoogleRateLimited(30))
    assert connected.post(f"/google/connections/{connected.conn_id}/refresh-locations").status_code == 429
    assert connected.get("/google/status").json()["connections"][0]["api_access"] == "approved"


def _approved_draft(connected, fake, body="Thank you, call us for a discount!"):
    fake.reviews = [greview(1)]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    did = connected.post(f"/reviews/{rid}/drafts", json={"body": body}).json()["id"]
    assert connected.post(f"/reply-drafts/{did}/approve", json={}).json()["status"] == "approved"
    return rid, did


def test_reply_google_rejects_on_publish_is_failed_not_published(connected, fake):
    rid, did = _approved_draft(connected, fake)
    fake.reply_to_review = lambda at, acct, loc, review_id, comment: {"comment": comment, "state": "REJECTED", "policy_violation": "ADVERTISING_AND_SOLICITATION"}
    r = connected.post(f"/reply-drafts/{did}/publish").json()
    assert r["status"] == "failed" and r["published_at"] is None and "advertising and solicitation" in r["failure_reason"]
    review = connected.get(f"/reviews/{rid}").json()
    assert review["review"]["google_reply_text"] is None and review["review"]["google_reply_state"] == "REJECTED"
    assert review["review"]["reply_state"] == "failed" and review["logs"][0]["success"] is False


def test_pending_reply_is_published_with_its_state_and_a_later_rejection_corrects_it(connected, fake):
    rid, did = _approved_draft(connected, fake)
    fake.reply_to_review = lambda at, acct, loc, review_id, comment: {"comment": comment, "state": "PENDING", "policy_violation": None}
    assert connected.post(f"/reply-drafts/{did}/publish").json()["status"] == "published"
    assert connected.get(f"/reviews/{rid}").json()["review"]["google_reply_state"] == "PENDING"
    # the next sync shows Google moderated it away
    rejected = greview(1, reply="Thank you, call us for a discount!")
    rejected.reply_state, rejected.reply_policy_violation = "REJECTED", "ADVERTISING_AND_SOLICITATION"
    fake.reviews = [rejected]
    connected.post("/google/sync")
    review = connected.get(f"/reviews/{rid}").json()
    assert review["review"]["google_reply_text"] is None and review["review"]["reply_state"] == "failed"
    assert "Google rejected this reply" in review["drafts"][0]["failure_reason"]


def test_reply_longer_than_googles_byte_limit_is_refused_when_drafting(connected, fake):
    fake.reviews = [greview(1)]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    assert connected.post(f"/reviews/{rid}/drafts", json={"body": "\u0927" * 1400}).status_code == 422  # 1400 characters, 4200 bytes
    assert connected.post(f"/reviews/{rid}/drafts", json={"body": "\u0927" * 1300}).status_code == 201
