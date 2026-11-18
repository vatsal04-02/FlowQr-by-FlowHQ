"""Admin-managed businesses: created by a platform administrator for shops that will never log in.

Covers: no user is ever created; managed Launch access and its limits; multiple locations; duplicate protection with an audited override; cards (QR and NFC) working for an ownerless business;
tenant isolation and admin-only access; the offline agreement record (never a personal acceptance); optional claiming (off by default, expiry, revocation, allowlist audit, no-existing-owner guard)."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import entitlements as ent
from app.services import provisioning as prov
from app.services.ai_usage import log_generation, quota_exceeded
from app.services.mailer import OUTBOX
from tests.conftest import make_business, make_user, owner_exec, owner_query
from tests.test_card_inventory import new_batch, scan
from tests.test_qr import UA, UA2

REVIEW = "https://g.page/r/CRoKUnique123/review"


def payload(**kw):
    n = uuid.uuid4().hex[:6]
    base = {"name": f"Sharma Sweets {n}", "category": "Sweet shop", "contact_name": "Ramesh Sharma", "phone": f"98{uuid.uuid4().int % 10**8:08d}", "city": "Kanpur",
            "address": "12 Mall Road", "review_url": f"https://g.page/r/Sh{n}Ab12/review"}
    base.update(kw)
    return base


def create(admin, **kw):
    r = admin.post("/admin/tenants", json=payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def counts():
    return owner_query("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM auth_sessions)")[0]


def sub_of(tid):
    cols = "plan, status, source, provider, trial_ends_at, trial_started_at, current_period_end, razorpay_subscription_id, cashfree_subscription_id, review_generations, review_replies, max_locations"
    return dict(zip([c.strip() for c in cols.split(",")], owner_query(f"SELECT {cols} FROM subscriptions WHERE tenant_id = :t", t=tid)[0]))


def entitlements(tid):
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        return ent.for_tenant(db, uuid.UUID(str(tid)))


def live_card(admin, tenant_id, location_id):
    b, cards = new_batch(admin, 2)
    r = admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": tenant_id, "location_id": location_id, "activate": True})
    assert r.status_code == 200, r.text
    return cards[0]


# ============================================================================================================================ 1. no user, managed Launch access
def test_a_business_is_created_without_any_user_membership_session_or_password(admin):
    before = counts()
    b = create(admin)
    assert counts() == before  # not one user, membership or session was created
    assert b["origin"] == "admin" and b["user_account_created"] is False
    row = owner_query("SELECT origin, created_by::text, updated_by::text, onboarding_completed, contact_name, phone FROM tenants WHERE id = :t", t=b["id"])[0]
    assert row[0] == "admin" and row[1] == row[2] and row[3] is True and row[4] == "Ramesh Sharma" and row[5].startswith("+91 98")
    assert owner_query("SELECT count(*) FROM memberships WHERE tenant_id = :t", t=b["id"])[0][0] == 0
    assert owner_query("SELECT count(*) FROM invitations WHERE tenant_id = :t", t=b["id"])[0][0] == 0


def test_the_new_business_has_launch_managed_access_with_no_trial_no_billing_and_the_200_200_limits(admin):
    b = create(admin)
    s = sub_of(b["id"])
    assert (s["plan"], s["status"], s["source"]) == ("starter", "manual", "manual")
    assert s["provider"] is None and s["razorpay_subscription_id"] is None and s["cashfree_subscription_id"] is None  # no provider: nothing can ever bill it
    assert s["trial_ends_at"] is None and s["trial_started_at"] is None and s["current_period_end"] is None  # no trial clock, no renewal date
    assert (s["review_generations"], s["review_replies"]) == (200, 200)
    e = entitlements(b["id"])
    assert e.active and e.status == "manual" and e.plan == "starter" and (e.review_generations, e.review_replies) == (200, 200)
    assert "keyword_tracking" not in e.features and "growth_agent" not in e.features  # Launch, not Growth
    assert owner_query("SELECT count(*) FROM payments WHERE tenant_id = :t", t=b["id"])[0][0] == 0
    assert "managed_access_granted" in [r[0] for r in owner_query("SELECT kind FROM subscription_events WHERE tenant_id = :t", t=b["id"])]


def test_the_monthly_ai_limits_are_enforced_per_business_and_usage_and_cost_are_tracked(admin):
    b = create(admin)
    other = create(admin)
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert quota_exceeded(db, uuid.UUID(b["id"]), "review_assist") is False
        for _ in range(200):
            log_generation(db, tenant_id=uuid.UUID(b["id"]), kind="review_assist", provider="x", model="m", language="en", input_chars=10, output_chars=10, status="ok", started=time.monotonic(),
                           usage={"prompt_tokens": 10, "completion_tokens": 5, "calls": 1, "cost": 0.001, "model": "m"})
        db.commit()
        assert quota_exceeded(db, uuid.UUID(b["id"]), "review_assist") is True  # the 200 writings are used up
        assert quota_exceeded(db, uuid.UUID(b["id"]), "reply_draft") is False  # replies are a separate allowance
        assert quota_exceeded(db, uuid.UUID(other["id"]), "review_assist") is False  # and another business is unaffected
    u = admin.get(f"/admin/tenants/{b['id']}").json()["ai_usage"]
    assert u["review_writings"] == {"used": 200, "limit": 200} and u["replies"] == {"used": 0, "limit": 200} and u["generations_logged"] == 200 and u["cost_usd"] > 0.19 and u["active"] is True


def test_revoking_managed_access_stops_the_ai_features_but_not_the_cards_and_restore_brings_it_back(admin, client):
    b = create(admin)
    loc = b["location"]["id"]
    card = live_card(admin, b["id"], loc)
    assert admin.post(f"/admin/tenants/{b['id']}/managed-access", json={"action": "revoke", "note": "client stopped using it"}).json() == {"state": "revoked", "status": "expired"}
    e = entitlements(b["id"])
    assert not e.active and e.reason == "trial_ended" or not e.active
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert quota_exceeded(db, uuid.UUID(b["id"]), "review_assist") is True
    body = scan(client, card, "qr", UA)  # the card and the plain review page still work: they never needed a subscription
    assert body["state"] == "ok" and body["review_url"] == b["location"]["review_url"]
    assert admin.post(f"/admin/tenants/{b['id']}/managed-access", json={"action": "restore", "note": "back again"}).json() == {"state": "managed", "status": "manual"}
    assert entitlements(b["id"]).active
    kinds = [r[0] for r in owner_query("SELECT kind FROM subscription_events WHERE tenant_id = :t ORDER BY created_at", t=b["id"])]
    assert "managed_access_revoked" in kinds and "managed_access_restored" in kinds
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action IN ('admin.managed_access_revoked', 'admin.managed_access_restored')", t=b["id"])[0][0] == 2


def test_managed_access_controls_refuse_a_business_that_has_its_own_trial_or_plan(admin, biz_a):
    r = admin.post(f"/admin/tenants/{biz_a.tenant_id}/managed-access", json={"action": "revoke", "note": "should not work"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_managed"
    assert sub_of(biz_a.tenant_id)["status"] == "trialing"  # untouched


def test_suspending_an_admin_managed_business_works_through_the_existing_control(admin, client):
    b = create(admin)
    card = live_card(admin, b["id"], b["location"]["id"])
    assert admin.post(f"/admin/tenants/{b['id']}/suspend", json={"reason": "non-payment of the offline fee"}).status_code == 204
    assert scan(client, card, "qr", UA)["state"] == "inactive"
    assert admin.post(f"/admin/tenants/{b['id']}/unsuspend").status_code == 204
    assert scan(client, card, "qr", UA2)["state"] == "ok"


# ============================================================================================================================ 2. validation
@pytest.mark.parametrize("bad", [
    {"review_url": "http://g.page/r/x/review"}, {"review_url": "https://evil.example.com/review"}, {"review_url": "javascript:alert(1)"}, {"website": "http://shop.example.com"},
    {"website": "javascript:alert(1)"}, {"email": "not-an-email"}, {"phone": ""}, {"phone": "12"}, {"name": "x"}, {"city": ""}, {"surprise": "field"}, {"agreement": {"method": "carrier pigeon", "confirm": True}},
])
def test_invalid_input_is_refused_and_creates_nothing(admin, bad):
    before = owner_query("SELECT count(*) FROM tenants")[0][0]
    r = admin.post("/admin/tenants", json=payload(**bad))
    assert r.status_code == 422, (bad, r.text)
    assert owner_query("SELECT count(*) FROM tenants")[0][0] == before


def test_a_business_can_be_created_before_its_review_link_is_known_and_says_so(admin):
    b = create(admin, review_url=None)
    d = admin.get(f"/admin/tenants/{b['id']}").json()
    assert d["tenant"]["onboarding_status"] == "incomplete" and d["locations"][0]["has_review_link"] is False


def test_names_and_text_are_trimmed_and_the_location_defaults_to_the_business_name(admin):
    b = create(admin, name="   Gupta   Medical   Store  ", location_name=None)
    assert b["name"] == "Gupta Medical Store" and b["location"]["name"] == "Gupta Medical Store"


# ============================================================================================================================ 3. locations
def test_several_locations_can_be_added_and_edited_and_the_plan_cap_bypass_is_audited(admin):
    b = create(admin)
    tid = b["id"]
    for i in range(3):
        r = admin.post(f"/admin/tenants/{tid}/locations", json={"name": f"Branch {i}", "city": "Kanpur", "review_url": f"https://g.page/r/Br{i}xyz99/review"})
        assert r.status_code == 201, r.text
    locs = admin.get(f"/admin/tenants/{tid}").json()["locations"]
    assert len(locs) == 4 and entitlements(tid).max_locations == 1  # four locations on a one-location plan: the admin path is not capped
    bypass = [r[0]["plan_limit_bypassed"] for r in owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'admin.location_create' ORDER BY created_at", t=tid)]
    assert bypass == [True, True, True]
    lid = locs[1]["id"]
    r = admin.patch(f"/admin/tenants/{tid}/locations/{lid}", json={"name": "Renamed branch", "phone": "9811122233", "review_url": "https://g.page/r/Renamed77/review"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed branch" and r.json()["review_url"].endswith("Renamed77/review") and r.json()["phone"].startswith("+91")
    assert admin.patch(f"/admin/tenants/{tid}/locations/{lid}", json={"review_url": "https://evil.example.com/x"}).status_code == 422


def test_a_location_cannot_be_edited_through_another_business(admin):
    a, b = create(admin), create(admin)
    r = admin.patch(f"/admin/tenants/{b['id']}/locations/{a['location']['id']}", json={"name": "hijack"})
    assert r.status_code == 404
    assert owner_query("SELECT name FROM locations WHERE id = :i", i=a["location"]["id"])[0][0] != "hijack"


def test_deactivating_a_location_with_live_cards_needs_confirmation(admin, client):
    b = create(admin)
    card = live_card(admin, b["id"], b["location"]["id"])
    url = f"/admin/tenants/{b['id']}/locations/{b['location']['id']}"
    r = admin.patch(url, json={"is_active": False})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required" and r.json()["detail"]["current"]["live_cards"] == 1
    assert scan(client, card, "qr", UA)["state"] == "ok"
    assert admin.patch(url, json={"is_active": False, "confirm": True}).status_code == 200
    assert scan(client, card, "qr", UA2)["state"] == "inactive"


# ============================================================================================================================ 4. cards work with no shopkeeper account
def test_a_card_assigned_to_a_new_business_works_for_qr_and_nfc_with_no_login_anywhere(admin, client):
    before = counts()
    b = create(admin)
    card = live_card(admin, b["id"], b["location"]["id"])
    q = scan(client, card, "qr", UA)
    n = scan(client, card, "nfc", UA2)
    for body in (q, n):
        assert body["state"] == "ok" and body["business"]["name"] == b["name"] and body["review_url"] == b["location"]["review_url"] and "url" not in body
    assert (q["channel"], n["channel"]) == ("qr", "nfc")
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()["totals"]
    assert (a["qr_scans"], a["nfc_taps"]) == (1, 1)  # analytics are collected with nobody logged in
    assert admin.put(f"/admin/cards/{card['id']}/destination", json={"url": "https://example.org/shop-review", "confirm": True}).status_code == 200  # and the admin manages the destination
    assert scan(client, card, "qr", {"User-Agent": UA["User-Agent"] + " b"})["url"] == "https://example.org/shop-review"
    assert counts() == before  # still not one user or membership


def test_cards_can_be_assigned_to_an_existing_self_service_business_as_before(admin, biz_a, client):
    card = live_card(admin, biz_a.tenant_id, biz_a.location_id)
    assert scan(client, card, "qr", UA)["business"]["name"] == "Alpha Physio"


def test_a_card_cannot_be_assigned_to_another_businesss_location(admin):
    a, b = create(admin), create(admin)
    _, cards = new_batch(admin, 1)
    r = admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": a["id"], "location_id": b["location"]["id"]})
    assert r.status_code == 400 and owner_query("SELECT tenant_id FROM qr_cards WHERE id = :i", i=cards[0]["id"])[0][0] is None


def test_moving_a_card_between_admin_businesses_still_needs_confirmation_and_clears_the_destination(admin, client):
    a, b = create(admin), create(admin)
    card = live_card(admin, a["id"], a["location"]["id"])
    admin.put(f"/admin/cards/{card['id']}/destination", json={"url": "https://example.org/a", "confirm": True})
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": b["id"], "location_id": b["location"]["id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required"
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": b["id"], "location_id": b["location"]["id"], "confirm": True}).json()["destination_url"] is None
    assert scan(client, card, "qr", UA)["business"]["name"] == b["name"]


# ============================================================================================================================ 5. duplicates
def test_a_look_alike_business_is_warned_about_with_the_reason_and_only_created_with_an_audited_reason(admin):
    first = create(admin, name="Annapurna Bakery", city="Lucknow", phone="9876500011", email="owner@annapurna.example")
    probe = {"name": "ANNAPURNA  bakery!", "city": "lucknow", "phone": "98765 00011", "email": "OWNER@annapurna.example", "review_url": None}
    r = admin.post("/admin/tenants/duplicate-check", json=probe)
    assert r.status_code == 200
    m = r.json()["matches"]
    assert len(m) == 1 and m[0]["id"] == first["id"] and {"Same name in the same city", "Same phone number", "Same email"} <= set(m[0]["reasons"])
    before = owner_query("SELECT count(*) FROM tenants")[0][0]
    r = admin.post("/admin/tenants", json=payload(name="Annapurna Bakery", city="Lucknow", phone="9876500011"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicates_found" and r.json()["detail"]["matches"][0]["id"] == first["id"]
    assert owner_query("SELECT count(*) FROM tenants")[0][0] == before  # nothing created by the warning
    assert admin.post("/admin/tenants", json=payload(name="Annapurna Bakery", city="Lucknow", phone="9876500011", duplicate_reason="short")).status_code == 422  # a real reason is mandatory
    r = admin.post("/admin/tenants", json=payload(name="Annapurna Bakery", city="Lucknow", phone="9876500011", duplicate_reason="Second shop of the same family, different street"))
    assert r.status_code == 201
    meta = owner_query("SELECT metadata FROM audit_logs WHERE entity_id = :t AND action = 'admin.business_create'", t=r.json()["id"])[0][0]
    assert meta["duplicate_reason"] == "Second shop of the same family, different street" and meta["duplicates_overridden"] == [first["id"]]


def test_duplicates_are_found_by_phone_email_google_place_and_name_alone_including_self_service_businesses(admin, biz_a):
    t = create(admin, name="Zed Opticals", phone="9811100022", city="Agra", review_url="https://g.page/r/PlaceZed991/review")
    def matches(**kw):
        return {m["id"]: set(m["reasons"]) for m in admin.post("/admin/tenants/duplicate-check", json={"name": "Totally Different Name", **kw}).json()["matches"]}
    assert matches(phone="+91 98111-00022") == {t["id"]: {"Same phone number"}}
    assert matches(review_url="https://g.page/r/PlaceZed991/review?foo=1") == {t["id"]: {"Same Google place (review link)"}}
    assert matches(review_url="https://g.page/r/Another55/review") == {}
    assert matches(phone="9999900000") == {}
    assert biz_a.tenant_id in {m["id"] for m in admin.post("/admin/tenants/duplicate-check", json={"name": "alpha physio"}).json()["matches"]}  # a self-service business is matched too (other test businesses share the name)
    named = admin.post("/admin/tenants/duplicate-check", json={"name": "Zed Opticals", "city": "Delhi"}).json()["matches"]
    assert named[0]["reasons"] == ["Same name"]  # same name, different city: still shown, with the honest reason


def test_unrelated_businesses_are_not_flagged(admin):
    create(admin, name="Raj Hardware", phone="9811100033", city="Patna")
    assert admin.post("/admin/tenants/duplicate-check", json={"name": "Raj Electricals", "city": "Patna", "phone": "9811100044"}).json()["matches"] == []


# ============================================================================================================================ 6. edit and the directory
def test_editing_a_business_records_who_and_what_and_rejects_unknown_fields(admin):
    b = create(admin)
    r = admin.patch(f"/admin/tenants/{b['id']}", json={"contact_name": "Suresh", "email": "suresh@shop.example", "website": "https://shop.example.com", "category": "Grocery"})
    assert r.status_code == 200 and r.json()["contact_name"] == "Suresh" and r.json()["email"] == "suresh@shop.example"
    assert admin.patch(f"/admin/tenants/{b['id']}", json={"origin": "self_service"}).status_code == 422  # origin and ownership fields cannot be edited
    assert admin.patch(f"/admin/tenants/{b['id']}", json={"is_active": False}).status_code == 422
    assert admin.patch(f"/admin/tenants/{b['id']}", json={"website": "http://insecure.example"}).status_code == 422
    meta = owner_query("SELECT metadata FROM audit_logs WHERE entity_id = :t AND action = 'admin.business_edit'", t=b["id"])[0][0]
    assert meta["fields"] == ["category", "contact_name", "email", "website"]  # field names only, no personal values in the audit entry
    d = admin.get(f"/admin/tenants/{b['id']}").json()["tenant"]
    assert d["created_by"] == d["updated_by"] == "root@flowhq-admin.example.com" and d["origin"] == "admin"


def test_the_directory_shows_contact_phone_cards_status_and_filters_by_search_origin_and_onboarding(admin, biz_a):
    ready = create(admin, name="Directory Ready Store", contact_name="Meena Devi", phone="9822200011", city="Jaipur")
    incomplete = create(admin, name="Directory Incomplete Store", phone="9822200022", city="Jaipur", review_url=None)
    live = create(admin, name="Directory Live Store", phone="9822200033", city="Jaipur")
    live_card(admin, live["id"], live["location"]["id"])

    def listing(**p):
        return {r["id"]: r for r in admin.get("/admin/tenants", params={"limit": 200, **p}).json()["items"]}
    rows = listing(search="Directory")
    assert {ready["id"], incomplete["id"], live["id"]} == set(rows)
    r = rows[live["id"]]
    assert r["contact_name"] == "Ramesh Sharma" and r["phone"].startswith("+91 98222") and r["locations"] == 1 and r["cards"] == 1 and r["active_cards"] == 1 and r["onboarding_status"] == "live" and r["origin"] == "admin"
    assert rows[ready["id"]]["onboarding_status"] == "ready" and rows[incomplete["id"]]["onboarding_status"] == "incomplete" and rows[ready["id"]]["owner_email"] is None
    assert set(listing(search="meena", origin="admin")) == {ready["id"]} or ready["id"] in listing(search="Meena Devi")
    assert set(listing(search="98222 00033")) == {live["id"]}  # by phone digits, however typed
    assert set(listing(search="Jaipur", onboarding="incomplete")) == {incomplete["id"]}
    assert set(listing(search="Directory", onboarding="live")) == {live["id"]}
    assert biz_a.tenant_id in listing(origin="self_service") and biz_a.tenant_id not in listing(origin="admin")
    assert listing(search="Alpha Physio")[biz_a.tenant_id]["onboarding_status"] == "has_account"
    assert admin.get("/admin/tenants", params={"onboarding": "nonsense"}).status_code == 422


# ============================================================================================================================ 7. the offline agreement record
def test_an_offline_agreement_is_recorded_as_an_administrators_statement_never_the_shopkeepers_acceptance(admin):
    b = create(admin, agreement={"method": "in_person", "note": "Explained in Hindi at the shop", "confirm": True})
    d = admin.get(f"/admin/tenants/{b['id']}").json()
    a = d["agreements"]
    assert len(a) == 1 and a[0]["method"] == "in_person" and a[0]["terms_version"] == prov.TERMS_VERSION and a[0]["recorded_by"] == "root@flowhq-admin.example.com" and a[0]["recorded_at"]
    assert a[0]["note"] == "Explained in Hindi at the shop" and "NOT the shopkeeper personally accepting" in a[0]["statement"] and "does NOT confirm that anyone is 18" in a[0]["statement"]
    assert d["tenant"]["agreement_recorded"] is True
    meta = owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'admin.business_agreement_recorded'", t=b["id"])[0][0]
    assert meta["personal_acceptance"] is False and meta["method"] == "in_person"
    assert owner_query("SELECT count(*) FROM users WHERE age_confirmed_at IS NOT NULL AND email LIKE :e", e=f"%{b['id'][:6]}%")[0][0] == 0  # no age confirmation exists for anyone because of this


def test_an_agreement_can_be_added_later_needs_the_admins_confirmation_and_a_known_method(admin):
    b = create(admin)
    assert admin.get(f"/admin/tenants/{b['id']}").json()["tenant"]["agreement_recorded"] is False
    assert admin.post(f"/admin/tenants/{b['id']}/agreement", json={"method": "phone"}).status_code == 422  # confirm is mandatory
    assert admin.post(f"/admin/tenants/{b['id']}/agreement", json={"method": "telepathy", "confirm": True}).status_code == 422
    r = admin.post(f"/admin/tenants/{b['id']}/agreement", json={"method": "whatsapp", "confirm": True, "note": "Agreed on WhatsApp"})
    assert r.status_code == 201 and r.json()["method"] == "whatsapp" and "NOT the shopkeeper" in r.json()["statement"]
    assert admin.post(f"/admin/tenants/{b['id']}/agreement", json={"method": "phone", "confirm": True}).status_code == 201
    assert len(admin.get(f"/admin/tenants/{b['id']}").json()["agreements"]) == 2  # append-only: a second record does not replace the first


def test_the_agreement_table_is_append_only_for_the_app_and_isolated_per_tenant(admin, biz_b):
    from sqlalchemy import text
    b = create(admin, agreement={"method": "paper", "confirm": True})
    privs = {r[0] for r in owner_query("SELECT privilege_type FROM information_schema.role_table_grants WHERE table_name = 'tenant_agreements' AND grantee = 'flowqr_app'")}
    assert privs == {"SELECT", "INSERT"}
    with SessionLocal() as db:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(biz_b.tenant_id)})
        db.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
        assert db.execute(text("SELECT count(*) FROM tenant_agreements")).scalar() == 0
    assert b["id"]


# ============================================================================================================================ 8. admin-only, isolation
ADMIN_ROUTES = [
    ("post", "/admin/tenants/duplicate-check", {"name": "Some Shop"}), ("post", "/admin/tenants", None), ("patch", "/admin/tenants/{t}", {"category": "x"}), ("post", "/admin/tenants/{t}/locations", {"name": "Branch"}),
    ("patch", "/admin/tenants/{t}/locations/{l}", {"name": "New"}), ("post", "/admin/tenants/{t}/agreement", {"method": "phone", "confirm": True}),
    ("post", "/admin/tenants/{t}/managed-access", {"action": "revoke", "note": "nope"}), ("post", "/admin/tenants/{t}/claim", {"email": "a@b.example", "delivery": "link"}),
    ("post", "/admin/tenants/{t}/claim/{l}/revoke", None),
]


def test_every_provisioning_route_is_closed_to_anonymous_callers_and_to_every_business(admin, biz_a, biz_b):
    b = create(admin)
    anon = TestClient(app, base_url="http://testserver")
    for method, path, body in ADMIN_ROUTES:
        url = "/api/v1" + path.format(t=b["id"], l=b["location"]["id"])
        r = anon.request(method.upper(), url, json=body if body is not None else payload())
        assert r.status_code in (401, 403), (method, path, r.status_code)
        for who in (biz_a, biz_b):
            r = getattr(who, method)(path.format(t=b["id"], l=b["location"]["id"]), json=body if body is not None else payload())
            assert r.status_code == 403, (method, path, r.status_code)
    assert owner_query("SELECT count(*) FROM tenants WHERE name LIKE 'Sharma Sweets%' AND created_by IS NULL")[0][0] == 0  # nothing was created by a caller that was refused


def test_a_business_owner_cannot_see_or_touch_an_admin_created_business(admin, biz_a):
    b = create(admin)
    _, cards = new_batch(admin, 1)
    assert biz_a.get("/tenant").json()["id"] == biz_a.tenant_id
    assert biz_a.get("/locations").json() and all(l["id"] != b["location"]["id"] for l in biz_a.get("/locations").json())
    assert biz_a.get(f"/locations/{b['location']['id']}").status_code == 404
    assert biz_a.patch(f"/locations/{b['location']['id']}", json={"name": "hijack"}).status_code == 404
    admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": b["id"], "location_id": b["location"]["id"], "activate": True})
    assert all(c["id"] != cards[0]["id"] for c in biz_a.get("/cards").json())


# ============================================================================================================================ 9. optional claiming
@pytest.fixture()
def claims_on(monkeypatch):
    monkeypatch.setattr(settings, "claim_invitations_enabled", True)


def test_claim_invitations_are_off_by_default(admin):
    assert settings.claim_invitations_enabled is False
    b = create(admin)
    r = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "owner@shop.example", "delivery": "link"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "claims_disabled"
    assert admin.get(f"/admin/tenants/{b['id']}").json()["claim"]["enabled"] is False
    assert owner_query("SELECT count(*) FROM invitations WHERE tenant_id = :t", t=b["id"])[0][0] == 0


def test_a_copyable_whatsapp_link_is_created_audited_expiring_and_stored_only_as_a_hash(admin, claims_on):
    b = create(admin, phone="9812345678")
    r = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "Owner@Shop.Example", "delivery": "link"})
    assert r.status_code == 201, r.text
    out = r.json()
    token = out["link"].split("token=")[1]
    assert out["link"].startswith(settings.frontend_url.rstrip("/") + "/accept-invite?token=") and out["email"] == "owner@shop.example" and out["email_sent"] is None
    assert out["whatsapp_url"].startswith("https://wa.me/919812345678?text=") and "accept-invite" in out["whatsapp_url"].replace("%3F", "?").replace("%2F", "/")
    row = owner_query("SELECT role::text, token_hash, expires_at, accepted_at, revoked_at, email FROM invitations WHERE tenant_id = :t", t=b["id"])[0]
    assert row[0] == "owner" and token not in row[1] and len(row[1]) == 64 and row[3] is None and row[4] is None and row[5] == "owner@shop.example"
    ttl = (row[2] - utcnow()).total_seconds() / 3600
    assert settings.claim_invitation_ttl_hours - 1 < ttl <= settings.claim_invitation_ttl_hours
    assert owner_query("SELECT count(*) FROM registration_allowlist WHERE email = 'owner@shop.example'")[0][0] == 1
    acts = {r[0] for r in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t", t=b["id"])}
    assert {"admin.claim_invitation_created", "admin.allowlist_added_for_claim"} <= acts
    assert not any(token in str(r) for r in owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t", t=b["id"]))  # the token is never in the audit log
    d = admin.get(f"/admin/tenants/{b['id']}").json()["claim"]
    assert d["invitations"][0]["state"] == "open" and "link" not in str(d)


def test_an_email_invitation_is_sent_and_reported_honestly(admin, claims_on):
    b = create(admin)
    n = len(OUTBOX)
    out = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "mail@shop.example", "delivery": "email"}).json()
    assert out["delivery"] == "email" and out["link"] is None and out["whatsapp_url"] is None and out["email_sent"] is True  # the link is in the email, not the response
    assert len(OUTBOX) == n + 1 and OUTBOX[-1]["to"] == "mail@shop.example" and "accept-invite?token=" in OUTBOX[-1]["body"]


def test_only_one_open_claim_at_a_time_and_revocation_blocks_acceptance(admin, claims_on):
    b = create(admin)
    first = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "one@shop.example", "delivery": "link"}).json()
    second = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "two@shop.example", "delivery": "link"}).json()
    states = {i["id"]: i["state"] for i in admin.get(f"/admin/tenants/{b['id']}").json()["claim"]["invitations"]}
    assert states[first["invitation_id"]] == "revoked" and states[second["invitation_id"]] == "open"
    u1 = make_user("one@shop.example")
    assert u1.post("/invitations/accept", json={"token": first["link"].split("token=")[1]}).status_code == 400  # revoked
    assert admin.post(f"/admin/tenants/{b['id']}/claim/{second['invitation_id']}/revoke").status_code == 200
    u2 = make_user("two@shop.example")
    assert u2.post("/invitations/accept", json={"token": second["link"].split("token=")[1]}).status_code == 400
    assert owner_query("SELECT count(*) FROM memberships WHERE tenant_id = :t", t=b["id"])[0][0] == 0
    assert admin.post(f"/admin/tenants/{b['id']}/claim/{uuid.uuid4()}/revoke").status_code == 404


def test_an_expired_invitation_cannot_be_accepted(admin, claims_on):
    b = create(admin)
    out = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "late@shop.example", "delivery": "link"}).json()
    owner_exec("UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE tenant_id = :t", t=b["id"])
    assert make_user("late@shop.example").post("/invitations/accept", json={"token": out["link"].split("token=")[1]}).status_code == 400
    assert admin.get(f"/admin/tenants/{b['id']}").json()["claim"]["invitations"][0]["state"] == "expired"


def test_claiming_makes_the_shopkeeper_owner_keeps_the_cards_and_data_and_cannot_be_repeated(admin, claims_on, client):
    b = create(admin, agreement={"method": "phone", "confirm": True})
    card = live_card(admin, b["id"], b["location"]["id"])
    out = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "claim@shop.example", "delivery": "link"}).json()
    token = out["link"].split("token=")[1]
    wrong = make_user("someone-else@example.com")
    assert wrong.post("/invitations/accept", json={"token": token}).status_code == 400  # a different account cannot use it
    owner = make_user("claim@shop.example")
    assert owner.post("/invitations/accept", json={"token": token}).status_code == 200
    assert owner_query("SELECT role::text FROM memberships WHERE tenant_id = :t", t=b["id"]) == [("owner",)]
    assert owner.post("/invitations/accept", json={"token": token}).status_code == 400  # one use only
    assert [c["card_code"] for c in owner.get("/cards").json()] == [card["card_code"]]  # the shopkeeper now sees the card the admin assigned
    assert scan(client, card, "qr", UA)["state"] == "ok"
    assert "tenant.claimed" in {r[0] for r in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t", t=b["id"])}
    d = admin.get(f"/admin/tenants/{b['id']}").json()
    assert d["tenant"]["owner_email"] == "claim@shop.example" and d["tenant"]["onboarding_status"] == "has_account" and d["claim"]["has_owner"] is True and len(d["agreements"]) == 1
    r = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "again@shop.example", "delivery": "link"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_claimed"


def test_an_owner_invitation_is_refused_if_the_business_gained_an_owner_in_the_meantime(admin, claims_on):
    b = create(admin)
    out = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "late-owner@shop.example", "delivery": "link"}).json()
    rival = make_user("rival@example.com")
    owner_exec("INSERT INTO memberships (id, tenant_id, user_id, role, all_locations, created_at, updated_at) SELECT gen_random_uuid(), :t, id, 'owner', true, now(), now() FROM users WHERE email = 'rival@example.com'", t=b["id"])
    late = make_user("late-owner@shop.example")
    r = late.post("/invitations/accept", json={"token": out["link"].split("token=")[1]})
    assert r.status_code == 400 and "already has an owner" in r.text
    assert owner_query("SELECT count(*) FROM memberships WHERE tenant_id = :t AND role = 'owner'", t=b["id"])[0][0] == 1 and rival.email


def test_the_allowlist_entry_lets_the_shopkeeper_register_when_registration_is_otherwise_closed(admin, claims_on, monkeypatch):
    monkeypatch.setattr(settings, "registration_mode", "allowlist")
    b = create(admin)
    http = TestClient(app, base_url="http://testserver")
    body = {"password": "Str0ng-Passw0rd!x", "age_confirmed": True, "full_name": "Shop Owner"}
    assert http.post("/api/v1/auth/register", json={"email": "newowner@shop.example", **body}).status_code in (403, 422, 400)  # not listed: refused
    admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": "newowner@shop.example", "delivery": "link"})
    assert TestClient(app, base_url="http://testserver").post("/api/v1/auth/register", json={"email": "newowner@shop.example", **body}).status_code == 201  # listed by the claim: allowed
    row = owner_query("SELECT note FROM registration_allowlist WHERE email = 'newowner@shop.example'")[0][0]
    assert "Claim invitation" in row


def test_staff_invitations_still_cannot_make_an_owner(biz_a):
    r = biz_a.post("/staff/invitations", json={"email": "x@y.example", "role": "owner"})
    assert r.status_code in (403, 422)


# ============================================================================================================================ 10. regression of the self-service path
def test_self_service_business_creation_is_unchanged(biz_a):
    assert owner_query("SELECT origin, created_by FROM tenants WHERE id = :t", t=biz_a.tenant_id)[0] == ("self_service", None)
    assert sub_of(biz_a.tenant_id)["status"] == "trialing"  # still the 7-day trial, not managed access
    assert owner_query("SELECT count(*) FROM memberships WHERE tenant_id = :t AND role = 'owner'", t=biz_a.tenant_id)[0][0] == 1


def test_pure_helpers_are_precise():
    assert prov.norm_name("  Shree  Ram-Medical Store! ") == "shreerammedicalstore"
    assert prov.last10("+91 98765-43210") == "9876543210" and prov.last10("12345") is None
    assert prov.place_key("https://g.page/r/CRoKAbc123/review") == "gpage:crokabc123"
    assert prov.place_key("https://search.google.com/local/writereview?placeid=ChIJxyz") == "placeid:chijxyz" and prov.place_key("https://example.com/x") is None and prov.place_key(None) is None
    assert prov.whatsapp_url("98123 45678", "hi there").startswith("https://wa.me/919812345678?text=hi%20there")
    assert prov.whatsapp_url(None, "x") == "https://wa.me/?text=x"
