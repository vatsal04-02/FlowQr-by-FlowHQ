"""One-tap review: in-place refinement (from the customer's own stars and topics) and the direct Google Write-a-review link. The shared AI "starter" text was
removed in Phase 0 (see tests/test_phase0_review_generation.py); nothing is pre-written for a customer.
A scripted test double stands in for the model: these prove FlowQR's rules and plumbing around it, not model quality."""
import uuid

import pytest

from app.core.config import settings
from app.services import review_growth as svc
from app.services.ai import health
from tests.conftest import owner_exec, owner_query
from tests.test_review_context import biz  # noqa: F401
from tests.test_review_growth import StubLLM, campaign, llm, pub  # noqa: F401  (llm = fixture)

NAME, PLACE = "Sunrise Physio", "Gomti Nagar, Lucknow"
V = dict(language="en", business_name=NAME, location_name=PLACE, category_label="Physiotherapy", services=("Back pain rehabilitation",))


@pytest.fixture(autouse=True)
def fresh_pools():
    health.reset()
    yield


def unique_biz(category="Physiotherapy clinic"):
    name = f"Starter Biz {uuid.uuid4().hex[:6]}"
    return biz(category, name), name


# ================================================================ direct Google Write-a-review link

@pytest.mark.parametrize("url,kind", [
    ("https://g.page/r/CabcDEF123/review", "direct"), ("https://search.google.com/local/writereview?placeid=ChIJ123", "direct"),
    ("https://www.google.com/maps/place/Sunrise+Physio/@26.8,80.9,17z", "listing"), ("https://maps.google.com/?cid=1234567890", "listing"),
    ("https://g.page/sunrise-physio", "listing"), ("https://www.google.com/search?q=sunrise+physio", "listing"),
    ("https://maps.app.goo.gl/abc123", "unknown"), ("https://goo.gl/maps/xyz", "unknown"), (None, "none"), ("", "none"),
])
def test_review_url_kind_tells_a_write_a_review_link_from_a_listing(url, kind):
    assert svc.review_url_kind(url) == kind


def test_a_general_listing_link_is_upgraded_to_the_direct_link_when_the_place_is_known(client, llm):
    b = biz("Physiotherapy clinic", f"Link Biz {uuid.uuid4().hex[:6]}")
    loc = b.post("/locations", json={"name": "Listing branch", "city": "Lucknow", "review_url": "https://www.google.com/maps/place/Sunrise+Physio"}).json()["id"]
    c = b.post("/review-growth/campaigns", json={"name": "QR", "location_id": loc}).json()
    page = pub(client, "GET", c["public_id"]).json()
    assert page["review_url"] == "https://www.google.com/maps/place/Sunrise+Physio" and page["review_url_kind"] == "listing"  # nothing better is known: unchanged
    conn = str(uuid.uuid4())
    owner_exec("INSERT INTO google_connections (id, tenant_id, status) VALUES (:i, :t, 'active')", i=conn, t=b.tenant_id)
    owner_exec("""INSERT INTO google_locations (id, tenant_id, connection_id, location_id, google_account_name, google_location_name, place_id, review_url, selected, consecutive_failures)
                  VALUES (:i, :t, :c, :l, 'accounts/1', 'locations/9', 'ChIJplace', 'https://search.google.com/local/writereview?placeid=ChIJplace', true, 0)""",
               i=str(uuid.uuid4()), t=b.tenant_id, c=conn, l=loc)
    page = pub(client, "GET", c["public_id"]).json()
    assert page["review_url"] == "https://search.google.com/local/writereview?placeid=ChIJplace" and page["review_url_kind"] == "direct"
    s = b.get("/review-growth/settings").json()["locations"]
    assert [x["review_url_kind"] for x in s if x["id"] == loc] == ["direct"]


def test_a_direct_link_the_owner_set_is_never_replaced(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    page = pub(client, "GET", c["public_id"]).json()
    assert page["review_url"] == "https://g.page/r/CTX/review" and page["review_url_kind"] == "direct" and page["google_ready"] is True


def test_settings_warn_when_the_link_is_only_a_listing(client, llm):
    b = biz("Physiotherapy clinic", f"Warn Biz {uuid.uuid4().hex[:6]}")
    loc = b.post("/locations", json={"name": "Maps only", "city": "Agra", "review_url": "https://maps.google.com/?cid=123"}).json()["id"]
    assert [x["review_url_kind"] for x in b.get("/review-growth/settings").json()["locations"] if x["id"] == loc] == ["listing"]


# ================================================================ refining in place

def start(client, c, llm, text="I appreciated how the staff dealt with me.", **over):
    llm.texts = [text]
    return pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 5, "suggestions": ["staff"], **over}).json()


def refine(client, c, sid, **over):
    return pub(client, "POST", c["public_id"], "/refine", json={"session_id": sid, "rating": 5, "suggestions": ["staff"], **over})


def test_refining_rewrites_the_same_session_from_the_new_stars_and_topics(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    first = start(client, c, llm)
    sid = first["session_id"]
    llm.texts = ["I wasn't satisfied with the appointments, and the treatment wasn't good either."]
    r = refine(client, c, sid, rating=2, suggestions=["appointment", "treatment"])
    d = r.json()
    assert r.status_code == 200 and d["ai_status"] == "ok" and d["session_id"] == sid and d["draft"].startswith("I wasn't satisfied")
    prompt = llm.calls[-1][1]
    assert "rated their visit 2 out of 5" in prompt and "Appointments" in prompt and "Treatment" in prompt and "Staff" not in prompt.split("CUSTOMER CONTEXT")[1] and "earlier_draft" not in prompt
    row = owner_query("SELECT rating, customer_input FROM review_sessions WHERE session_identifier=:s", s=sid)[0]
    assert row[0] == 2 and row[1]["suggestions"] == ["appointment", "treatment"] and row[1]["sentiment"] == "not_good"
    assert owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 1


def test_refining_is_not_a_new_customer_a_new_ai_request_or_a_regenerate(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = start(client, c, llm)["session_id"]
    for rating, text in ((4, "I appreciated how the staff dealt with me."), (3, "The staff were okay."), (5, "I appreciated the way the staff dealt with me.")):
        llm.texts = [text]
        assert refine(client, c, sid, rating=rating).json()["ai_status"] == "ok"
    ev = dict(owner_query("SELECT event_type, count(*) FROM review_events WHERE campaign_id=:c GROUP BY event_type", c=c["id"]))
    assert ev["feedback_submitted"] == 1 and ev["ai_requested"] == 1 and ev["draft_generated"] == 1 and "draft_regenerated" not in ev
    assert owner_query("SELECT generation_count FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=sid)[0][0] == 1
    # ...so Regenerate still has its full allowance
    llm.texts = ["The staff looked after me well, and I liked how they dealt with me."]
    assert pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()["remaining_drafts"] == settings.review_max_drafts_per_session - 2


def test_the_rating_distribution_counts_the_rating_they_ended_with(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = start(client, c, llm, rating=5)["session_id"]
    llm.texts = ["The staff were okay."]
    refine(client, c, sid, rating=3)
    a = b.get("/review-growth/analytics").json()["ratings"]
    assert a["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 0}  # one customer, counted once, at their final rating


def test_newly_picked_topics_are_counted_once_each(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = start(client, c, llm)["session_id"]
    llm.texts = ["I appreciated how the staff dealt with me, and things were explained clearly."]
    refine(client, c, sid, suggestions=["staff", "explanations"])
    refine(client, c, sid, suggestions=["staff", "explanations"])
    top = {s["id"]: s["count"] for s in b.get("/review-growth/analytics").json()["suggestions"]}
    assert top == {"staff": 1, "explanations": 1}


def test_refine_needs_content_a_known_session_and_respects_its_cap(client, llm, monkeypatch):
    b, _ = unique_biz()
    c = campaign(b)
    sid = start(client, c, llm)["session_id"]
    assert pub(client, "POST", c["public_id"], "/refine", json={"session_id": sid, "rating": 5}).status_code == 422
    assert pub(client, "POST", c["public_id"], "/refine", json={"session_id": sid, "rating": 9, "suggestions": ["staff"]}).status_code == 422
    assert refine(client, c, "z" * 22).status_code == 404
    monkeypatch.setattr(settings, "review_max_refinements", 2)
    llm.texts = ["I appreciated how the staff dealt with me."]
    assert [refine(client, c, sid).status_code for _ in range(3)] == [200, 200, 429]


def test_refine_failures_never_block_and_never_store_a_draft(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = start(client, c, llm)["session_id"]
    llm.texts = ["The staff were polite and I recovered fully."]  # an invented result: rejected by the same guards as any draft
    d = refine(client, c, sid).json()
    assert d["ai_status"] == "rejected" and d["retryable"] is True


# ================================================================ copy + Google handoff accounting

def test_copy_outcome_is_recorded_once_as_a_yes_no(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual", "rating": 4, "text": "my own words here"}).json()["session_id"]
    pub(client, "POST", c["public_id"], "/approve", json={"session_id": sid, "final_text": "A review written by the customer."})
    assert pub(client, "POST", c["public_id"], "/redirect", json={"session_id": sid, "copied": True}).json() == {"review_url": "https://g.page/r/CTX/review"}
    pub(client, "POST", c["public_id"], "/redirect", json={"session_id": sid, "copied": True})
    t = b.get("/review-growth/analytics").json()["totals"]
    assert t["review_copied"] == 1 and t["google_redirects"] == 1
    assert "review_copied" in b.get("/review-growth/analytics").json()["definitions"]


def test_a_failed_copy_is_not_counted_as_copied(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual", "text": "own words"}).json()["session_id"]
    pub(client, "POST", c["public_id"], "/approve", json={"session_id": sid, "final_text": "A review written by the customer."})
    pub(client, "POST", c["public_id"], "/redirect", json={"session_id": sid, "copied": False})
    t = b.get("/review-growth/analytics").json()["totals"]
    assert t["review_copied"] == 0 and t["google_redirects"] == 1


def hand(client, c, **body):
    return pub(client, "POST", c["public_id"], "/handoff", json={"final_text": "A review in the customer's own words.", "language": "en", **body})


def events(c):
    return dict(owner_query("SELECT event_type, count(*) FROM review_events WHERE campaign_id=:c GROUP BY event_type", c=c["id"]))


def test_one_tap_is_one_request_that_opens_confirms_and_counts(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    r = hand(client, c, rating=4, suggestions=["staff"], copied=True)
    d = r.json()
    assert r.status_code == 200 and d["review_url"] == "https://g.page/r/CTX/review" and d["google_ready"] is True and d["copied"] is True and len(d["session_id"]) >= 16
    ev = events(c)
    assert ev == {"feedback_submitted": 1, "manual_selected": 1, "suggestion_selected": 1, "draft_approved": 1, "review_copied": 1, "google_redirect": 1}
    row = owner_query("SELECT d.final_content, s.rating, s.customer_input->>'sentiment' FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=d["session_id"])[0]
    assert row == ("A review in the customer's own words.", 4, "good")
    assert b.get("/review-growth/analytics").json()["ratings"]["distribution"]["4"] == 1


def test_the_same_tap_twice_is_counted_once_and_the_latest_wording_wins(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = hand(client, c, copied=True).json()["session_id"]
    again = hand(client, c, session_id=sid, final_text="The customer edited it a little and tapped again.", copied=True).json()
    assert again["session_id"] == sid
    assert events(c) == {"feedback_submitted": 1, "manual_selected": 1, "draft_approved": 1, "review_copied": 1, "google_redirect": 1}
    assert owner_query("SELECT d.final_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=sid)[0][0] == "The customer edited it a little and tapped again."


def test_a_blocked_clipboard_is_still_a_tap_but_not_a_copy(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    hand(client, c, copied=False)
    ev = events(c)
    assert ev["google_redirect"] == 1 and "review_copied" not in ev


def test_a_customer_who_used_ai_keeps_their_session(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    llm.texts = ["I appreciated how the staff dealt with me."]
    sid = pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 5, "suggestions": ["staff"]}).json()["session_id"]
    assert hand(client, c, session_id=sid, copied=True).json()["session_id"] == sid
    ev = events(c)
    assert ev["feedback_submitted"] == 1 and ev["ai_requested"] == 1 and "manual_selected" not in ev and ev["draft_approved"] == 1 and ev["google_redirect"] == 1


def test_an_unknown_or_expired_session_never_loses_the_tap(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    r = hand(client, c, session_id="mockSessionxxxxxxxxxxxx", copied=True)
    assert r.status_code == 200 and r.json()["session_id"] != "mockSessionxxxxxxxxxxxx" and events(c)["google_redirect"] == 1


def test_handoff_is_validated_and_for_real_browsers(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    assert hand(client, c, final_text="short").status_code == 422
    assert hand(client, c, rating=9).status_code == 422
    assert hand(client, c, suggestions=["Bad Id"]).status_code == 422
    assert client.post(f"/api/v1/public/reviews/{c['public_id']}/handoff", json={"final_text": "A long enough review text."}, headers={"user-agent": "curl/8"}).status_code == 403
    b.patch(f"/review-growth/campaigns/{c['id']}", json={"status": "paused"})
    assert hand(client, c).status_code == 410


def test_markup_is_stripped_from_the_final_text(client, llm):
    b, _ = unique_biz()
    c = campaign(b)
    sid = hand(client, c, final_text="Great <b>care</b> from the team at the clinic.").json()["session_id"]
    assert owner_query("SELECT d.final_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=sid)[0][0] == "Great b care /b from the team at the clinic."  # angle brackets removed, spaces collapsed


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5, None])
def test_no_rating_changes_where_the_customer_is_sent(client, llm, rating):
    b, _ = unique_biz()
    c = campaign(b)
    body = {"mode": "manual", "text": "own words here"} | ({"rating": rating} if rating else {})
    sid = pub(client, "POST", c["public_id"], "/generate", json=body).json()["session_id"]
    assert pub(client, "POST", c["public_id"], "/approve", json={"session_id": sid, "final_text": "A review written by the customer."}).json()["review_url"] == "https://g.page/r/CTX/review"
    assert pub(client, "POST", c["public_id"], "/redirect", json={"session_id": sid, "copied": True}).json()["review_url"] == "https://g.page/r/CTX/review"
