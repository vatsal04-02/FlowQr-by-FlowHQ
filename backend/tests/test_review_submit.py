"""The review-submission provider seam.

REAL: the supported handoff route and the guarantees around a provider (consent, equal access, honesty, no double submission).
TEST DOUBLE (clearly not Google): `FakeDirect` below, used only to prove those guarantees hold the day an approved provider exists.
NOT TESTED, because it does not exist: any actual submission to Google. No such API is used anywhere; see docs/GOOGLE_DIRECT_REVIEWS.md."""
import uuid

import pytest

from app.core.config import settings
from app.services.review_submit import DIRECT, HANDOFF, GoogleDirectProvider, SubmitRequest, SubmitResult, SubmitUnavailable, provider_for
from tests.conftest import owner_query
from tests.test_review_context import biz  # noqa: F401
from tests.test_review_growth import campaign, pub  # noqa: F401


class FakeDirect:
    """TEST DOUBLE standing in for a future approved provider. It records what it was asked to submit and returns whatever the test scripts."""

    name, mode = "fake_direct", "direct"

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def available(self, location):
        return True

    def capabilities(self):
        return {"requires_customer_google_sign_in": True, "submits_for_customer": True}

    def submit(self, request: SubmitRequest):
        self.calls.append(request)
        r = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(r, Exception):
            raise r
        return r


PUBLISHED = SubmitResult(status="published", external_ref="google-review-123")
TEXT = "The customer's own final wording, exactly as they approved it."


def unique_biz():
    return biz("Physiotherapy clinic", f"Submit Biz {uuid.uuid4().hex[:6]}")


@pytest.fixture()
def direct(monkeypatch):
    def enable(*results):
        fake = FakeDirect(*(results or (PUBLISHED,)))
        monkeypatch.setattr("app.api.v1.review_public.provider_for", lambda loc: fake)
        return fake
    return enable


def sub(client, c, **body):
    return pub(client, "POST", c["public_id"], "/submit", json={"final_text": TEXT, "rating": 5, "consent": True, "language": "en", **body})


def events(c):
    return dict(owner_query("SELECT event_type, count(*) FROM review_events WHERE campaign_id=:c GROUP BY event_type", c=c["id"]))


# ================================================================ today: nothing is submitted for the customer, and nothing pretends to be

def test_by_default_the_only_route_is_the_supported_handoff(client):
    b = unique_biz()
    c = campaign(b)
    page = pub(client, "GET", c["public_id"]).json()
    assert page["submission"] == {"mode": "handoff", "requires_customer_google_sign_in": False, "submits_for_customer": False}
    r = sub(client, c)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "direct_unavailable" and "post it on Google yourself" in r.json()["detail"]["message"]
    assert events(c) == {"scan": 1}  # opening the page is counted; nothing was confirmed, counted or stored by the refused submit
    assert owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0


def test_a_configuration_flag_alone_can_never_switch_direct_submission_on(client, monkeypatch):
    monkeypatch.setattr(settings, "google_direct_submission", "approved")
    b = unique_biz()
    c = campaign(b)
    assert GoogleDirectProvider.implemented is False  # flips only with a real, verified, approved implementation
    assert pub(client, "GET", c["public_id"]).json()["submission"]["mode"] == "handoff"
    assert sub(client, c).status_code == 409


def test_the_google_direct_provider_refuses_to_submit_and_calls_nothing():
    assert DIRECT.available(None) is False and provider_for(None) is HANDOFF
    with pytest.raises(SubmitUnavailable) as e:
        DIRECT.submit(SubmitRequest(tenant_id=1, location_id=1, rating=5, text=TEXT, language="en"))
    assert e.value.code == "not_authorized"
    with pytest.raises(SubmitUnavailable) as h:
        HANDOFF.submit(SubmitRequest(tenant_id=1, location_id=1, rating=5, text=TEXT, language="en"))
    assert h.value.code == "handoff_only"


def test_no_google_review_api_is_called_anywhere_in_the_application():
    """Guard against an undocumented endpoint, a private API or browser automation being added quietly."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    bad = re.compile(r"playwright|selenium|puppeteer|mybusiness\.googleapis\.com/v4/accounts/[^\"']*/reviews[^\"']*:(?:create|insert|post)|/maps/api/review|createReview|postReview", re.I)
    offenders = [str(f.relative_to(root)) for f in root.rglob("*.py") if bad.search(f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_supported_handoff_route_keeps_working(client):
    b = unique_biz()
    c = campaign(b)
    r = pub(client, "POST", c["public_id"], "/handoff", json={"final_text": TEXT, "rating": 2, "copied": True}).json()
    assert r["review_url"] == "https://g.page/r/CTX/review" and r["copied"] is True
    assert events(c).get("review_submitted") is None  # a Google TAP is never reported as a submitted review


# ================================================================ when an approved provider exists, the rules still hold

def test_the_page_is_told_when_direct_submission_is_available(client, direct):
    direct()
    c = campaign(unique_biz()[0] if False else unique_biz())
    assert pub(client, "GET", c["public_id"]).json()["submission"] == {"mode": "direct", "requires_customer_google_sign_in": True, "submits_for_customer": True}


def test_a_consented_submission_sends_exactly_the_customers_text_and_rating(client, direct):
    fake = direct()
    b = unique_biz()
    c = campaign(b)
    r = sub(client, c, rating=4, suggestions=["staff"])
    d = r.json()
    assert r.status_code == 200 and d["status"] == "published" and d["published"] is True
    req = fake.calls[0]
    assert req.text == TEXT and req.rating == 4 and req.language == "en"  # not rewritten, shortened, softened or re-rated by anything in between
    assert events(c) == {"feedback_submitted": 1, "manual_selected": 1, "suggestion_selected": 1, "draft_approved": 1, "review_submitted": 1}
    assert owner_query("SELECT d.final_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=d["session_id"])[0][0] == TEXT
    assert b.get("/review-growth/analytics").json()["totals"]["direct_submitted"] == 1


@pytest.mark.parametrize("body", [{"consent": False}, {}])
def test_without_explicit_consent_nothing_is_submitted_or_stored(client, direct, body):
    fake = direct()
    c = campaign(unique_biz())
    payload = {"final_text": TEXT, "rating": 5, "language": "en", **body}
    assert pub(client, "POST", c["public_id"], "/submit", json=payload).status_code == 422
    assert fake.calls == [] and events(c) == {}


def test_every_rating_takes_the_same_road_equal_access(client, direct):
    fake = direct()
    c = campaign(unique_biz())
    out = [(sub(client, c, rating=n, final_text=f"Review number {n}, written by the customer.").json()["published"]) for n in (1, 2, 3, 4, 5)]
    assert out == [True] * 5 and sorted(r.rating for r in fake.calls) == [1, 2, 3, 4, 5]  # a 1-star review is submitted exactly like a 5-star one


def test_a_double_tap_never_submits_twice(client, direct):
    fake = direct()
    c = campaign(unique_biz())
    first = sub(client, c).json()
    again = sub(client, c, session_id=first["session_id"]).json()
    assert again["published"] is True and again["already"] is True and len(fake.calls) == 1
    assert events(c)["review_submitted"] == 1


@pytest.mark.parametrize("result", [
    SubmitResult(status="pending"), SubmitResult(status="rejected"), SubmitResult(status="failed"),
    SubmitResult(status="published", external_ref=None),  # "published" without Google's confirmation reference is NOT published
])
def test_success_is_claimed_only_when_google_confirmed_it(client, direct, result):
    direct(result)
    c = campaign(unique_biz())
    d = sub(client, c).json()
    assert d["published"] is False and d["status"] in ("pending", "failed") and "post it on Google yourself" in d["message"] and d["review_url"] == "https://g.page/r/CTX/review"
    ev = events(c)
    assert "review_submitted" not in ev and ev["review_submit_failed"] == 1


@pytest.mark.parametrize("error,status,code", [
    (SubmitUnavailable("no", code="not_authorized"), 503, "not_authorized"), (RuntimeError("boom with secret-token"), 502, "submit_failed"),
])
def test_a_provider_failure_keeps_the_customers_review_and_a_fallback_link(client, direct, error, status, code):
    direct(error)
    b = unique_biz()
    c = campaign(b)
    r = sub(client, c)
    assert r.status_code == status and r.json()["detail"]["code"] == code and r.json()["detail"]["review_url"] == "https://g.page/r/CTX/review"
    assert "secret-token" not in r.text  # provider internals never reach the customer
    assert events(c)["review_submit_failed"] == 1 and "review_submitted" not in events(c)
    assert owner_query("SELECT count(*) FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.campaign_id=:c AND d.final_content IS NOT NULL", c=c["id"])[0][0] == 1  # their wording is kept


def test_submit_is_validated_and_for_real_browsers(client, direct):
    direct()
    c = campaign(unique_biz())
    assert sub(client, c, final_text="short").status_code == 422
    assert sub(client, c, rating=0).status_code == 422
    assert pub(client, "POST", c["public_id"], "/submit", json={"final_text": TEXT, "consent": True, "language": "en"}).status_code == 422  # rating required: it is their own
    assert client.post(f"/api/v1/public/reviews/{c['public_id']}/submit", json={"final_text": TEXT, "rating": 5, "consent": True}, headers={"user-agent": "curl/8"}).status_code == 403


def test_a_paused_campaign_does_not_submit(client, direct):
    fake = direct()
    b = unique_biz()
    c = campaign(b)
    b.patch(f"/review-growth/campaigns/{c['id']}", json={"status": "paused"})
    assert sub(client, c).status_code == 410 and fake.calls == []
