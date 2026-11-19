"""Meta price admin (second round, Phase 5): dated prices that are never overwritten, an append-only record of price checks, the free service allowance, and the warning shown while a price is unverified.

Rate rows and checks live in shared tables, so every test cleans up what it adds and leaves the tables as the migration made them."""
import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.base import utcnow
from app.services.whatsapp import pricing
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, grant_addon, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import ready_biz, send, svc_db, wm  # noqa: F401 - fixtures

SEED = {"marketing": ("1.0900", 0), "utility": ("0.1450", 0), "authentication": ("0.1450", 0), "service": ("0.1450", 1000)}


@pytest.fixture(autouse=True)
def tidy():
    yield
    owner_exec("DELETE FROM whatsapp_rate_verifications")
    owner_exec("DELETE FROM whatsapp_rates WHERE source LIKE 'TESTROW%'")


def rates(admin):
    r = admin.get("/admin/whatsapp/rates")
    assert r.status_code == 200, r.text
    return r.json()


def in_force(admin, category):
    return next(i for i in rates(admin)["items"] if i["category"] == category and i["in_force"])


def new_row(admin, **kw):
    body = {"category": "utility", "rate": "0.2000", "effective_from": utcnow().date().isoformat(), "source": "TESTROW checked against a test rate card", "verified": False, **kw}
    r = admin.post("/admin/whatsapp/rates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ===================================================================== the starting values
def test_the_october_2026_india_starting_values_are_loaded_and_marked_unverified(admin):
    rows = owner_query("SELECT category, rate, free_per_number_month, verified, source, currency FROM whatsapp_rates WHERE country = 'IN' AND effective_from = DATE '2026-10-01' ORDER BY category")
    assert {r[0]: (str(r[1]), r[2]) for r in rows} == SEED
    assert all(r[3] is False and "UNVERIFIED" in r[4] and "not yet checked" in r[4].lower() and r[5] == "INR" for r in rows)
    assert owner_query("SELECT count(*) FROM whatsapp_rate_verifications")[0][0] == 0  # nobody has checked them


def test_earlier_prices_are_kept_as_history_and_the_newest_dated_one_is_in_force(admin):
    jan = owner_query("SELECT category, rate FROM whatsapp_rates WHERE effective_from = DATE '2026-01-01' ORDER BY category")
    assert dict((c, str(r)) for c, r in jan) == {"authentication": "0.1150", "marketing": "0.8631", "service": "0.0000", "utility": "0.1150"}  # not overwritten
    got = rates(admin)
    for cat, (rate, free) in SEED.items():
        row = in_force(admin, cat)
        assert row["rate"] == rate and row["free_per_number_month"] == free and row["verified"] is False and row["verification"] is None and row["effective_from"] == "2026-10-01"
        assert sum(1 for i in got["items"] if i["category"] == cat) >= 2  # the January row is still listed
        assert sum(1 for i in got["items"] if i["category"] == cat and i["in_force"]) == 1
    assert sorted(got["unverified_in_use"]) == ["authentication", "marketing", "service", "utility"]


def test_only_a_platform_administrator_sees_or_changes_prices(admin):
    biz = make_business("Price Peeker")
    rid = in_force(admin, "marketing")["id"]
    assert biz.get("/admin/whatsapp/rates").status_code == 403
    assert biz.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "0.1", "effective_from": "2027-02-01", "source": "TESTROW rate card"}).status_code == 403
    assert biz.post(f"/admin/whatsapp/rates/{rid}/verification", json={"verified": True, "note": "I looked at the rate card"}).status_code == 403


# ===================================================================== adding a price never overwrites an old one
def test_a_new_price_is_a_new_dated_row_and_old_rows_are_untouched(admin):
    before = in_force(admin, "utility")
    row = new_row(admin, rate="0.2000", effective_from="2027-03-01")
    assert row["rate"] == "0.2000" and row["verified"] is False and row["free_per_number_month"] == 0
    assert in_force(admin, "utility")["id"] == before["id"]  # a future-dated price is not in force yet
    same = admin.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "0.3", "effective_from": "2027-03-01", "source": "TESTROW again"})
    assert same.status_code == 409 and same.json()["detail"]["code"] == "rate_exists"  # never overwritten
    assert owner_query("SELECT rate FROM whatsapp_rates WHERE id = :i", i=row["id"])[0][0] == Decimal("0.2000")
    assert admin.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "0.3", "effective_from": "2027-03-02", "source": "short"}).status_code == 422
    assert admin.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "0.3", "effective_from": "2027-03-02", "source": "TESTROW rate card", "free_per_number_month": -1}).status_code == 422
    assert admin.post("/admin/whatsapp/rates", json={"category": "fax", "rate": "0.3", "effective_from": "2027-03-02", "source": "TESTROW rate card"}).status_code == 422


def test_the_application_can_never_edit_or_delete_a_rate_or_a_check():
    role = settings.database_url.split("//")[1].split(":")[0]
    for table in ("whatsapp_rates", "whatsapp_rate_verifications"):
        for priv in ("UPDATE", "DELETE"):
            assert owner_query("SELECT has_table_privilege(:r, :t, :p)", r=role, t=f"public.{table}", p=priv)[0][0] is False, (table, priv)
        assert owner_query("SELECT has_table_privilege(:r, :t, 'INSERT')", r=role, t=f"public.{table}")[0][0] is True


# ===================================================================== verification is a separate, append-only record
def test_a_check_is_a_separate_record_and_the_screen_shows_the_latest_one(admin):
    row = in_force(admin, "marketing")
    r = admin.post(f"/admin/whatsapp/rates/{row['id']}/verification", json={"verified": True, "note": "Matches Meta's India rate card, page dated 1 Oct 2026"})
    assert r.status_code == 201 and r.json()["verified"] is True
    shown = in_force(admin, "marketing")
    assert shown["verified"] is True and shown["verification"]["note"].startswith("Matches Meta's India") and shown["verification"]["by"] and shown["verification"]["at"]
    assert owner_query("SELECT verified, rate FROM whatsapp_rates WHERE id = :i", i=row["id"])[0] == (False, Decimal("1.0900"))  # the rate row itself is untouched
    admin.post(f"/admin/whatsapp/rates/{row['id']}/verification", json={"verified": False, "note": "Meta changed its page, needs another look"})
    assert in_force(admin, "marketing")["verified"] is False  # the newest check wins
    assert owner_query("SELECT count(*) FROM whatsapp_rate_verifications WHERE rate_id = :i", i=row["id"])[0][0] == 2  # and the earlier one is kept
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'admin.whatsapp_rate_verification' AND entity_id::text = :i", i=str(row["id"]))[0][0] == 2


def test_a_check_needs_a_note_and_a_real_rate(admin):
    rid = in_force(admin, "utility")["id"]
    assert admin.post(f"/admin/whatsapp/rates/{rid}/verification", json={"verified": True, "note": "ok"}).status_code == 422
    assert admin.post(f"/admin/whatsapp/rates/{rid}/verification", json={"note": "A proper note about the check"}).status_code == 422
    missing = admin.post("/admin/whatsapp/rates/00000000-0000-0000-0000-000000000000/verification", json={"verified": True, "note": "A proper note about the check"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "rate_not_found"
    assert owner_query("SELECT count(*) FROM whatsapp_rate_verifications")[0][0] == 0


def test_adding_a_price_as_verified_records_the_check_the_same_way(admin):
    row = new_row(admin, effective_from="2027-04-01", verified=True)
    assert row["verified"] is True and row["verification"]["verified"] is True
    assert owner_query("SELECT count(*) FROM whatsapp_rate_verifications WHERE rate_id = :i", i=row["id"])[0][0] == 1


# ===================================================================== the free service allowance
def test_an_estimate_subtracts_the_free_allowance_and_says_so(wm, admin):
    with svc_db(uuid.uuid4()) as db:
        e = pricing.estimate(db, "service", 1500)
        assert (e["free_included"], e["billable"], e["amount"], e["rate"]) == (1000, 500, "72.50", "0.1450") and "1,000" in e["note"] and e["free_per_number_month"] == 1000
        assert pricing.estimate(db, "service", 400)["amount"] == "0.00" and pricing.estimate(db, "service", 400)["free_included"] == 400  # all inside the allowance
        used = pricing.estimate(db, "service", 500, already_used=800)  # 800 already used this month: only 200 free left
        assert (used["free_included"], used["billable"], used["amount"]) == (200, 300, "43.50")
        assert pricing.estimate(db, "service", 500, already_used=5000)["free_included"] == 0  # allowance gone
        m = pricing.estimate(db, "marketing", 10)
        assert (m["free_included"], m["billable"], m["amount"]) == (0, 10, "10.90")  # no allowance on offers


def test_a_message_inside_the_monthly_free_allowance_is_recorded_at_zero(wm, admin):
    new_row(admin, category="utility", rate="0.2000", free_per_number_month=1)  # dated today: in force now
    biz = ready_biz(admin, "Free Allowance")
    a = add_contact(biz, "98765 70001", utility=True, **OWNER)
    b = add_contact(biz, "98765 70002", utility=True, **OWNER)
    assert send(biz, a["id"], variables=["Asha", "Free Allowance", "https://g.page/r/x/review"]).ok
    assert send(biz, b["id"], variables=["Ravi", "Free Allowance", "https://g.page/r/x/review"]).ok
    rows = owner_query("SELECT est_rate FROM whatsapp_messages WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)
    assert [Decimal(r[0]) for r in rows] == [Decimal("0.0000"), Decimal("0.2000")]  # the first is free, the second is not


def test_a_category_without_an_allowance_is_always_charged_the_rate_in_force(wm, admin):
    with svc_db(uuid.uuid4()) as db:
        assert pricing.est_rate_for_send(db, uuid.uuid4(), "marketing") == Decimal("1.0900")
        assert pricing.est_rate_for_send(db, uuid.uuid4(), "utility") == Decimal("0.1450")
        assert pricing.est_rate_for_send(db, uuid.uuid4(), "service") == Decimal("0")  # a fresh number: the first 1,000 service messages are free
        assert pricing.est_rate_for_send(db, uuid.uuid4(), "carrier_pigeon") is None  # no rate, no claim


# ===================================================================== the owner sees a warning while the price in use is unverified
def test_owners_see_a_warning_above_cost_figures_until_the_prices_in_use_are_checked(wm, admin):
    biz = ready_biz(admin, "Warned Owner")
    u = biz.get("/whatsapp/usage").json()
    assert u["price_warning"] and "starting values" in u["price_warning"] and u["rates"]["marketing"]["verified"] is False and u["rates"]["marketing"]["warning"]
    for cat in ("marketing", "utility"):
        admin.post(f"/admin/whatsapp/rates/{in_force(admin, cat)['id']}/verification", json={"verified": True, "note": f"Matches Meta's India {cat} rate, checked today"})
    u2 = biz.get("/whatsapp/usage").json()
    assert u2["price_warning"] is None and u2["rates"]["marketing"]["verified"] is True and u2["rates"]["marketing"]["warning"] is None
    admin.post(f"/admin/whatsapp/rates/{in_force(admin, 'utility')['id']}/verification", json={"verified": False, "note": "Rate card changed, rechecking this one"})
    assert biz.get("/whatsapp/usage").json()["price_warning"]  # one unverified price in use is enough


def test_the_offer_preview_carries_the_same_warning_and_the_estimate_stays_labelled(wm, admin):
    with svc_db(uuid.uuid4()) as db:
        e = pricing.estimate(db, "marketing", 3)
        assert e["warning"] and e["verified"] is False and "not a bill" in e["note"].lower() and e["amount"] == "3.27"


def test_the_new_route_is_in_the_access_manifest_for_platform_administrators_only():
    lines = [ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/admin/whatsapp/rates" in ln]
    assert {(m, p): k for k, m, p in lines} == {("GET", "/api/v1/admin/whatsapp/rates"): "platform-admin", ("POST", "/api/v1/admin/whatsapp/rates"): "platform-admin",
                                                 ("POST", "/api/v1/admin/whatsapp/rates/{rate_id}/verification"): "platform-admin"}
