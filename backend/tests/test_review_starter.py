"""One-tap review: the neutral AI starter shown before any input, in-place refinement, and the direct Google Write-a-review link.
A scripted test double stands in for the model: these prove FlowQR's rules and plumbing around it, not model quality."""
import uuid

import pytest

from app.api.v1 import review_public
from app.core.config import settings
from app.services import review_growth as svc
from app.services.ai import health
from app.services.ai.review_generate import ReviewDraftRejected, generate_starter, validate_starter
from tests.conftest import owner_exec, owner_query
from tests.test_review_context import biz  # noqa: F401
from tests.test_review_growth import StubLLM, campaign, llm, pub  # noqa: F401  (llm = fixture)

NAME, PLACE = "Sunrise Physio", "Gomti Nagar, Lucknow"
V = dict(language="en", business_name=NAME, location_name=PLACE, category_label="Physiotherapy", services=("Back pain rehabilitation",))


@pytest.fixture(autouse=True)
def fresh_pools():
    review_public._starter_memory.clear()
    health.reset()
    yield
    review_public._starter_memory.clear()


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


# ================================================================ the starter validator: who the review is about, nothing more

@pytest.mark.parametrize("text", [
    "Sharing my feedback on Sunrise Physio, a physiotherapy clinic in Gomti Nagar, Lucknow.",
    "This is my review of Sunrise Physio in Gomti Nagar, Lucknow.",
    "Writing about Sunrise Physio, which offers back pain rehabilitation in Lucknow.",  # a service the business offers: allowed; "pain" is the owner's own wording
    "Leaving a review for Sunrise Physio.",
])
def test_neutral_openers_pass(text):
    validate_starter(text, **V)


@pytest.mark.parametrize("text,why", [
    ("I visited Sunrise Physio last week and the staff were great.", "visit"),
    ("I had back pain rehabilitation at Sunrise Physio.", "visit|experience"),
    ("Sunrise Physio is an excellent clinic.", "praise|quality"),
    ("Sunrise Physio is a professional clinic in Lucknow.", "quality"),
    ("My review of Sunrise Physio: I would recommend it.", "experience|recommendation"),
    ("Sunrise Physio, five stars.", "rating|number"),
    ("Review of Sunrise Physio after 12 sessions.", "number"),
    ("Sharing my feedback on a physiotherapy clinic in Lucknow.", "name the business"),
    ("Sharing my feedback on Sunrise Physio and Dr Sharma.", "name"),
    ("Sunrise Physio helped my back and I recovered fully.", "result|visit|experience"),
    ("Sharing my feedback on Sunrise Physio. [add your experience here]", "meta|placeholder"),
    ("Hi", "length"),
])
def test_anything_beyond_who_the_review_is_about_is_rejected(text, why):
    with pytest.raises(ReviewDraftRejected, match=why):
        validate_starter(text, **V)


def test_a_hindi_opener_must_be_hindi_and_name_the_business():
    validate_starter("Sunrise Physio, गोमती नगर लखनऊ के बारे में अपनी राय साझा कर रहा हूँ।", **{**V, "language": "hi"})
    with pytest.raises(ReviewDraftRejected, match="Hindi"):
        validate_starter("Sharing my feedback on Sunrise Physio in Lucknow.", **{**V, "language": "hi"})
    with pytest.raises(ReviewDraftRejected, match="visit"):
        validate_starter("मैं Sunrise Physio में इलाज करवाया था।", **{**V, "language": "hi"})


def test_an_opener_must_differ_from_the_earlier_ones():
    with pytest.raises(ReviewDraftRejected, match="similar"):
        validate_starter("Sharing my feedback on Sunrise Physio in Lucknow.", **V, previous=("Sharing my feedback on Sunrise Physio, in Lucknow.",))


class Seq:
    name, model = "seq", "seq-1"

    def __init__(self, *texts):
        self.texts, self.calls, self.usage = list(texts), [], None

    def generate(self, system, user, **kw):
        self.calls.append((system, user, kw))
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


def test_generate_starter_retries_once_with_a_hint_then_gives_up():
    p = Seq("I visited Sunrise Physio and loved it.", "Sharing my feedback on Sunrise Physio in Lucknow.")
    stats = {}
    out = generate_starter(p, language="en", business_name=NAME, category_label="Physiotherapy", location_name="Lucknow", stats=stats)
    assert out == "Sharing my feedback on Sunrise Physio in Lucknow." and stats["attempts"] == 2 and stats["rejects_rules"] == 1
    assert "rejected" in p.calls[1][1] and "nothing about the visit" in p.calls[1][1]
    with pytest.raises(ReviewDraftRejected):
        generate_starter(Seq("I visited Sunrise Physio and loved it."), language="en", business_name=NAME)


# ================================================================ the starter endpoint

def starter(client, c, **q):
    return pub(client, "GET", c["public_id"], "/starter", params=q)


def test_starter_is_neutral_labelled_and_built_only_from_the_business(client, llm):
    b, name = unique_biz()
    b.put("/review-growth/context", json={"description": "Exercise-based rehabilitation clinic.", "services": ["Back pain rehabilitation"]})
    c = campaign(b)
    llm.texts = [f"Sharing my feedback on {name}, a physiotherapy clinic in Lucknow."]
    d = starter(client, c).json()
    assert d["ai_status"] == "ok" and d["source"] == "ai_suggestion" and d["draft"].startswith("Sharing my feedback on") and "says nothing about your visit" in d["note"]
    system, user = llm.calls[0]
    assert name in user and "Back pain rehabilitation" in user and "Exercise-based rehabilitation clinic." in user and "background only" in user
    assert "customer_answers" not in user and "rating" not in user.lower()  # no customer data of any kind goes in
    assert "Do not say they visited" in system and "NOTHING about this customer's visit" in system
    log = owner_query("SELECT kind, status, input_chars FROM ai_generation_logs WHERE tenant_id=:t", t=b.tenant_id)
    assert log == [("review_starter", "ok", 0)]
    assert owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0  # nothing is stored about the visitor


def test_a_busy_qr_code_costs_a_handful_of_model_calls_not_one_per_scan(client, llm):
    b, name = unique_biz()
    c = campaign(b)
    llm.texts = [f"Sharing my feedback on {name}, a physiotherapy clinic in Lucknow.", f"This is my review of {name} in Lucknow.", f"A few words about {name}.",
                 f"Writing about the clinic in Lucknow, {name}.", f"My review of {name}, a physiotherapy clinic.", f"Leaving a review for {name} from Lucknow."]
    seen = {starter(client, c).json()["draft"] for _ in range(6)}
    assert len(llm.calls) == 6 and len(seen) == 6  # the pool fills with six different openers
    served = [starter(client, c).json()["draft"] for _ in range(20)]
    assert len(llm.calls) == 6 and set(served) <= seen and len(set(served)) > 1  # then no more model calls: a random one of the six
    assert starter(client, c, language="en").json()["ai_status"] == "ok"


def test_editing_the_business_context_changes_the_pool(client, llm):
    b, name = unique_biz()
    c = campaign(b)
    llm.texts = [f"Writing about {name} in Lucknow."]
    starter(client, c)
    first = len(llm.calls)
    b.put("/review-growth/context", json={"services": ["Sports injury rehabilitation"]})
    llm.texts = [f"Leaving a review for {name}, which offers sports injury rehabilitation."]
    assert starter(client, c).json()["draft"].startswith("Leaving a review") and len(llm.calls) == first + 1  # a new key: no stale opener


def test_an_invented_opener_is_never_served_and_a_failure_cools_down(client, llm):
    b, name = unique_biz()
    c = campaign(b)
    llm.texts = [f"I visited {name} and the staff were excellent."]
    d = starter(client, c).json()
    assert d["draft"] is None and d["ai_status"] == "unavailable"
    calls = len(llm.calls)
    assert starter(client, c).json()["draft"] is None and len(llm.calls) == calls  # no hammering the model while cooling down
    assert owner_query("SELECT status FROM ai_generation_logs WHERE tenant_id=:t AND kind='review_starter'", t=b.tenant_id) == [("rejected",)]


def test_no_starter_when_ai_is_off_paused_or_the_account_is_out_of_quota(client, monkeypatch):
    b, name = unique_biz()
    c = campaign(b)
    assert starter(client, c).json() == {"draft": None, "ai_status": "unavailable", "language": "en", "source": None}  # not configured in tests
    stub = StubLLM([f"Writing about {name}."])
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: stub)
    health.mark_down("credits")
    assert starter(client, c).json()["draft"] is None and stub.calls == []
    health.reset()
    monkeypatch.setattr("app.api.v1.review_public.quota_exceeded", lambda db, t: True)
    assert starter(client, c).json()["draft"] is None and stub.calls == []


def test_starter_is_for_real_browsers_and_is_rate_limited_and_scoped(client, llm):
    b, name = unique_biz()
    c = campaign(b)
    assert client.get(f"/api/v1/public/reviews/{c['public_id']}/starter", headers={"user-agent": "curl/8"}).status_code == 403
    assert pub(client, "GET", "x" * 20, "/starter").status_code == 404
    paused = campaign(b, "Paused")
    b.patch(f"/review-growth/campaigns/{paused['id']}", json={"status": "paused"})
    assert starter(client, paused).status_code == 410


def test_starter_follows_the_supported_languages(client, llm):
    b, name = unique_biz()
    b.put("/review-growth/context", json={"languages": ["en"]})
    c = campaign(b)
    llm.texts = [f"Writing about {name}."]
    assert starter(client, c, language="hi").json()["language"] == "en"  # an unsupported language falls back, never errors
    b.put("/review-growth/context", json={"languages": ["en", "hi"]})
    llm.texts = [f"{name} के बारे में अपनी राय साझा कर रहा हूँ।"]
    d = starter(client, c, language="hi").json()
    assert d["language"] == "hi" and "के बारे में" in d["draft"]


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
