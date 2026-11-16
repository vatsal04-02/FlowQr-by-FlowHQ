"""Set-up suggestions (business and address search, PIN lookup) and the rule that a new trial opens only after a card is on file.

Google is never called: the Places client gets a mock transport. What these tests pin:
  * the key stays on the server and is sent only as a header;
  * only the fields the forms need come back, shaped for the forms (street, city, state, PIN, a MOBILE number only, our category, Google's review link);
  * the per-person daily cap and the platform monthly cap refuse further calls, and every call and refusal is one row in the usage ledger;
  * without a key nothing is called and the forms stay manual;
  * a trial that is waiting for its card can be set up (first location) but cannot do anything else, and onboarding cannot be finished until the card is on file.
"""
import json
import uuid

import httpx
import pytest

from app.core.config import settings
from app.services import places_suggest as ps
from tests.conftest import make_user, owner_exec, owner_query

KEY = "AIza-test-places-key-do-not-leak"
SESSION = "11111111-2222-3333-4444-555555555555"

TUNDAY = {
    "id": "ChIJEfzCO7r9mzkRHBWpJxgYZmE",
    "displayName": {"text": "Tunday Kababi, Aminabad"},
    "formattedAddress": "168/6, Old Nazirabad Rd, Mohan Market, Khayali Ganj, Aminabad, Lucknow, Uttar Pradesh 226018, India",
    "nationalPhoneNumber": "078978 61786",
    "websiteUri": "https://www.tundaykababi.com/",
    "primaryType": "kebab_shop",
    "types": ["kebab_shop", "indian_restaurant", "restaurant", "food", "point_of_interest", "establishment"],
    "addressComponents": [
        {"longText": "168/6", "types": ["street_number"]}, {"longText": "Old Nazirabad Road", "types": ["route"]},
        {"longText": "Mohan Market", "types": ["neighborhood", "political"]}, {"longText": "Khayali Ganj", "types": ["sublocality_level_2", "sublocality", "political"]},
        {"longText": "Aminabad", "types": ["sublocality_level_1", "sublocality", "political"]}, {"longText": "Lucknow", "types": ["locality", "political"]},
        {"longText": "Lucknow", "types": ["administrative_area_level_3", "political"]}, {"longText": "Lucknow Division", "types": ["administrative_area_level_2", "political"]},
        {"longText": "Uttar Pradesh", "types": ["administrative_area_level_1", "political"]}, {"longText": "India", "types": ["country", "political"]},
        {"longText": "226018", "types": ["postal_code"]},
    ],
}
AUTOCOMPLETE = {"suggestions": [
    {"placePrediction": {"placeId": "ChIJEfzCO7r9mzkRHBWpJxgYZmE", "types": ["kebab_shop", "restaurant"], "structuredFormat": {
        "mainText": {"text": "Tunday Kababi, Aminabad"}, "secondaryText": {"text": "Old Nazirabad Road, Aminabad, Lucknow, Uttar Pradesh, India"}}}},
    {"queryPrediction": {"text": {"text": "not a place"}}},  # query predictions are ignored
]}


class Spy:
    """Records what the (fake) Google received and answers from `reply`."""

    def __init__(self, reply):
        self.calls: list[httpx.Request] = []
        self.reply = reply

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.reply(request)


def google(reply, monkeypatch) -> Spy:
    spy = Spy(reply)
    monkeypatch.setattr(ps, "get_client", lambda: ps.Client(KEY, transport=httpx.MockTransport(spy)))
    return spy


def ok_reply(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=AUTOCOMPLETE if request.url.path.endswith("places:autocomplete") else TUNDAY)


def ledger(user_id: str):
    return owner_query("SELECT operation, status, feature, tenant_id FROM api_usage_ledger WHERE user_id = :u AND feature = 'onboarding_suggest' ORDER BY created_at", u=user_id)


def uid(s) -> str:
    return s.http.get("/api/v1/auth/me").json()["user"]["id"]


# ---------------------------------------------------------------- off by default, signed-in only
def test_without_a_key_nothing_is_called_and_the_forms_stay_manual():
    u = make_user()
    r = u.get(f"/places/autocomplete?q=tunday&session={SESSION}")
    assert r.status_code == 200 and r.json() == {"enabled": False, "suggestions": []}
    assert u.get(f"/places/details?place_id=ChIJEfzCO7r9mzkRHBWpJxgYZmE&session={SESSION}").status_code == 404


def test_every_places_route_needs_a_signed_in_person(client):
    assert client.get(f"/api/v1/places/autocomplete?q=tunday&session={SESSION}").status_code == 401
    assert client.get(f"/api/v1/places/details?place_id=ChIJEfzCO7r9mzkRHBWpJxgYZmE&session={SESSION}").status_code == 401
    assert client.get("/api/v1/places/pincode/226018").status_code == 401


# ---------------------------------------------------------------- autocomplete
def test_autocomplete_returns_only_places_and_never_the_key(monkeypatch):
    spy = google(ok_reply, monkeypatch)
    u = make_user()
    r = u.get(f"/places/autocomplete?q=Tunday%20Kababi&session={SESSION}")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and len(body["suggestions"]) == 1
    s = body["suggestions"][0]
    assert s["place_id"] == "ChIJEfzCO7r9mzkRHBWpJxgYZmE" and s["title"].startswith("Tunday") and "Lucknow" in s["subtitle"]
    assert KEY not in r.text and KEY not in json.dumps(dict(r.headers))
    sent = spy.calls[0]
    assert sent.headers["X-Goog-Api-Key"] == KEY and KEY not in str(sent.url)  # header, never the URL
    payload = json.loads(sent.content)
    assert payload["includedRegionCodes"] == ["in"] and payload["sessionToken"] == SESSION and "includedPrimaryTypes" not in payload
    assert [(row[0], row[1], row[3]) for row in ledger(uid(u))] == [("autocomplete", "ok", None)]  # one ledger row, not tied to a business yet


def test_address_search_asks_google_for_addresses_only(monkeypatch):
    spy = google(ok_reply, monkeypatch)
    u = make_user()
    assert u.get(f"/places/autocomplete?q=12%20Park%20Road&kind=address&session={SESSION}").status_code == 200
    assert 1 <= len(json.loads(spy.calls[0].content)["includedPrimaryTypes"]) <= 5  # Google allows at most five


@pytest.mark.parametrize("url", [
    "/places/autocomplete?q=ab&session=" + SESSION,  # too short
    "/places/autocomplete?q=tunday&kind=nope&session=" + SESSION,
    "/places/autocomplete?q=tunday&session=short",
])
def test_bad_input_is_refused_before_google_is_called(url, monkeypatch):
    spy = google(ok_reply, monkeypatch)
    assert make_user().get(url).status_code == 422 and spy.calls == []


# ---------------------------------------------------------------- details
def test_details_fill_the_forms_and_build_google_s_review_link(monkeypatch):
    spy = google(ok_reply, monkeypatch)
    u = make_user()
    r = u.get(f"/places/details?place_id=ChIJEfzCO7r9mzkRHBWpJxgYZmE&session={SESSION}")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Tunday Kababi, Aminabad" and d["city"] == "Lucknow" and d["state"] == "Uttar Pradesh" and d["postal_code"] == "226018"
    assert d["address_line"] == "168/6 Old Nazirabad Road, Mohan Market, Khayali Ganj, Aminabad"
    assert d["area"] == "Aminabad" and d["website"] == "https://www.tundaykababi.com/"
    assert d["phone"] == "78978 61786"  # the 0 trunk prefix is dropped
    assert d["category"] == "Restaurant"
    assert d["review_url"] == "https://search.google.com/local/writereview?placeid=ChIJEfzCO7r9mzkRHBWpJxgYZmE"
    assert KEY not in r.text
    assert spy.calls[0].url.params["sessionToken"] == SESSION  # the same session as the typing, so Google bills one session


def test_the_city_is_the_largest_locality_google_lists():
    g = {**TUNDAY, "addressComponents": [{"longText": "Service Road", "types": ["route"]}, {"longText": "Semra", "types": ["locality", "political"]},
                                          {"longText": "Lucknow", "types": ["locality", "political"]}, {"longText": "Uttar Pradesh", "types": ["administrative_area_level_1"]}]}
    assert ps.shape_details(g)["city"] == "Lucknow"


def test_a_landline_or_foreign_number_is_left_for_the_owner_to_type():
    assert ps.indian_mobile("0522 400 1234") is None and ps.indian_mobile("+44 20 7946 0958") is None
    assert ps.indian_mobile("+91 98765 43210") == "98765 43210" and ps.indian_mobile(None) is None


@pytest.mark.parametrize("primary,types,expected", [
    ("physiotherapist", [], "Physiotherapy clinic"), ("dentist", [], "Dental clinic"), ("beauty_salon", [], "Salon / Spa"), ("hindu_temple", ["establishment"], None),
    ("jewelry_store", [], "Retail store"), ("north_indian_restaurant", [], "Restaurant"), ("gym", [], "Gym / Fitness"), (None, ["car_repair"], "Automobile service centre"),
])
def test_google_types_map_to_our_categories(primary, types, expected):
    assert ps.map_category(primary, types) == expected


def test_google_errors_become_friendly_messages_without_the_key(monkeypatch):
    for status, expect in ((403, 503), (404, 404), (500, 502)):
        google(lambda r, s=status: httpx.Response(s, json={"error": {"status": "X", "message": f"key {KEY} is bad"}}), monkeypatch)
        r = make_user().get(f"/places/details?place_id=ChIJEfzCO7r9mzkRHBWpJxgYZmE&session={SESSION}")
        assert r.status_code == expect and KEY not in r.text


def test_a_failed_autocomplete_does_not_break_the_form(monkeypatch):
    google(lambda r: httpx.Response(500, json={}), monkeypatch)
    r = make_user().get(f"/places/autocomplete?q=tunday&session={SESSION}")
    assert r.status_code == 200 and r.json()["suggestions"] == [] and "by hand" in r.json()["note"]


# ---------------------------------------------------------------- the spend limits
def test_a_person_has_a_daily_ceiling_and_refusals_are_recorded(monkeypatch):
    monkeypatch.setattr(settings, "places_suggest_user_daily_cap", 2)
    spy = google(ok_reply, monkeypatch)
    u = make_user()
    for _ in range(2):
        assert u.get(f"/places/autocomplete?q=tunday&session={SESSION}").json()["enabled"] is True
    r = u.get(f"/places/autocomplete?q=tunday&session={SESSION}")
    assert r.json()["enabled"] is False and "today" in r.json()["note"] and len(spy.calls) == 2
    assert u.get(f"/places/details?place_id=ChIJEfzCO7r9mzkRHBWpJxgYZmE&session={SESSION}").status_code == 429
    assert [row[1] for row in ledger(uid(u))] == ["ok", "ok", "refused", "refused"]
    other = make_user()  # one person's ceiling does not stop another
    assert other.get(f"/places/autocomplete?q=tunday&session={SESSION}").json()["enabled"] is True


def test_the_platform_has_a_monthly_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "places_suggest_user_daily_cap", 0)
    used = owner_query("SELECT count(*) FROM api_usage_ledger WHERE feature = 'onboarding_suggest' AND status = 'ok' AND created_at >= date_trunc('month', now())")[0][0]
    monkeypatch.setattr(settings, "places_suggest_monthly_cap", used + 1)
    google(ok_reply, monkeypatch)
    u = make_user()
    assert u.get(f"/places/autocomplete?q=tunday&session={SESSION}").json()["enabled"] is True
    r = u.get(f"/places/autocomplete?q=tunday&session={SESSION}")
    assert r.json()["enabled"] is False and "month" in r.json()["note"]


# ---------------------------------------------------------------- PIN codes
PIN_OK = [{"Status": "Success", "PostOffice": [
    {"Name": "Aminabad Park", "District": "Lucknow", "State": "Uttar Pradesh"}, {"Name": "Golaganj", "District": "Lucknow", "State": "Uttar Pradesh"},
    {"Name": "Ganesh Ganj (Lucknow)", "District": "Lucknow", "State": "Uttar Pradesh"}]}]


def test_a_pin_code_gives_city_state_and_areas():
    ps._pin_cache.clear()
    seen = []
    t = httpx.MockTransport(lambda r: (seen.append(str(r.url)), httpx.Response(200, json=PIN_OK))[1])
    got = ps.lookup_pincode("226018", transport=t)
    assert got == {"postal_code": "226018", "city": "Lucknow", "state": "Uttar Pradesh", "areas": ["Aminabad Park", "Ganesh Ganj", "Golaganj"]}
    assert ps.lookup_pincode("226018", transport=t) == got and len(seen) == 1  # cached: the directory is asked once


def test_an_unknown_pin_is_none_and_a_malformed_one_is_refused():
    ps._pin_cache.clear()
    none = httpx.MockTransport(lambda r: httpx.Response(200, json=[{"Status": "Error", "PostOffice": None}]))
    assert ps.lookup_pincode("999999", transport=none) is None
    for bad in ("12345", "abcdef", "0123456", "22601 8"):
        with pytest.raises(ps.SuggestError):
            ps.lookup_pincode(bad)


def test_the_pin_route_answers_404_for_unknown_and_422_for_malformed(monkeypatch):
    monkeypatch.setattr(ps, "lookup_pincode", lambda pin, transport=None: {"postal_code": pin, "city": "Lucknow", "state": "Uttar Pradesh", "areas": []} if pin == "226018" else None)
    u = make_user()
    assert u.get("/places/pincode/226018").json()["city"] == "Lucknow"
    assert u.get("/places/pincode/999999").status_code == 404
    monkeypatch.undo()
    assert u.get("/places/pincode/12ab").status_code == 422


# ---------------------------------------------------------------- the card gate
@pytest.fixture()
def payments_on(monkeypatch):
    """Razorpay is configured and new trials need a card."""
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc123")
    monkeypatch.setattr(settings, "razorpay_key_secret", "secret-for-tests")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec-for-tests")
    monkeypatch.setattr(settings, "trial_requires_card", True)


def new_business(name="Gate Cafe"):
    u = make_user()
    r = u.post("/tenants", json={"name": name, "category": "Restaurant", "language": "en"})
    assert r.status_code == 201, r.text
    u.tenant_id = r.json()["id"]
    return u


def test_a_trial_waiting_for_its_card_can_be_set_up_but_not_used_or_finished(payments_on):
    u = new_business()
    sub = u.get("/billing/subscription").json()
    assert sub["card_required"] is True and sub["active"] is False and sub["inactive_reason"] == "card_required"
    # setting up works: the first location can be added while the plan step is still ahead
    r = u.post("/locations", json={"name": "Main", "city": "Lucknow", "review_url": "https://search.google.com/local/writereview?placeid=ChIJEfzCO7r9mzkRHBWpJxgYZmE"})
    assert r.status_code == 201, r.text
    # but nothing that does work for the business does
    blocked = u.post("/google/connect")
    assert blocked.status_code == 402 and blocked.json()["detail"]["reason"] == "card_required"
    # and onboarding cannot be completed, so the app stays closed
    done = u.post("/tenant/complete-onboarding")
    assert done.status_code == 402 and done.json()["detail"]["code"] == "card_required"
    assert owner_query("SELECT onboarding_completed FROM tenants WHERE id = :t", t=u.tenant_id)[0][0] is False


def test_with_the_card_on_file_onboarding_finishes_and_the_trial_is_active(payments_on):
    u = new_business()
    assert u.post("/locations", json={"name": "Main"}).status_code == 201
    owner_exec("UPDATE subscriptions SET card_status = 'on_file' WHERE tenant_id = :t", t=u.tenant_id)
    assert u.post("/tenant/complete-onboarding").status_code == 200
    sub = u.get("/billing/subscription").json()
    assert sub["card_on_file"] is True and sub["active"] is True and sub["status"] == "trialing"


def test_the_set_up_exception_ends_when_onboarding_is_finished(payments_on):
    """A business that somehow finished onboarding while still waiting for a card gets no more free set-up calls."""
    u = new_business()
    assert u.post("/locations", json={"name": "Main"}).status_code == 201
    owner_exec("UPDATE tenants SET onboarding_completed = true WHERE id = :t", t=u.tenant_id)
    owner_exec("UPDATE subscriptions SET max_locations = 5 WHERE tenant_id = :t", t=u.tenant_id)
    r = u.post("/locations", json={"name": "Second"})
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "card_required"


def test_without_payments_nobody_is_ever_locked_out(monkeypatch):
    """The card rule is on, but no Razorpay keys exist: a card cannot be taken, so the trial opens normally (the site says 'no card needed' in this state too)."""
    monkeypatch.setattr(settings, "trial_requires_card", True)
    assert settings.razorpay_configured is False
    u = new_business("Open Cafe")
    sub = u.get("/billing/subscription").json()
    assert sub["card_required"] is False and sub["active"] is True
    assert u.post("/locations", json={"name": "Main"}).status_code == 201
    assert u.post("/tenant/complete-onboarding").status_code == 200
    assert u.get("/billing/plans").json()["trial_requires_card"] is False


def test_the_plans_endpoint_reports_the_rule_only_when_it_is_enforced(payments_on):
    assert make_user().http.get("/api/v1/billing/plans").json()["trial_requires_card"] is True
