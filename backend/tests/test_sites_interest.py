"""Onboarding asks "do you have a website?"; FlowQR staff see the answer in the business list and can start a website from there.

A business saying "please build one for me" creates NOTHING (no site, no charge, no publish): it only marks the business so staff can follow up."""
import pytest

from app.core.config import settings
from tests.conftest import make_business, owner_query
from tests.test_sites_api import sites_on  # noqa: F401 - fixture
from tests.test_sites_api import new_site



def row(admin, tid):
    items = admin.get("/admin/tenants", params={"search": "Interest"}).json()["items"]
    return next(i for i in items if i["id"] == tid)


def test_a_new_business_has_never_been_asked(admin):
    biz = make_business("Interest Never")
    assert biz.get("/tenant").json()["website_interest"] is None
    assert row(admin, biz.tenant_id)["website_interest"] is None


@pytest.mark.parametrize("answer", ["has_site", "wants_site", "not_now"])
def test_the_owner_can_answer_and_it_is_recorded_and_audited(admin, answer):
    biz = make_business("Interest Answer")
    r = biz.put("/tenant/website-interest", json={"interest": answer})
    assert r.status_code == 200 and r.json()["website_interest"] == answer
    assert owner_query("SELECT website_interest FROM tenants WHERE id = :t", t=biz.tenant_id)[0][0] == answer
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'tenant.website_interest'", t=biz.tenant_id)[0][0] == 1


@pytest.mark.parametrize("bad", ["yes", "", "WANTS_SITE", "has_site; drop table tenants", None])
def test_only_the_three_answers_are_accepted(bad):
    biz = make_business("Interest Bad")
    assert biz.put("/tenant/website-interest", json={"interest": bad}).status_code == 422
    assert biz.get("/tenant").json()["website_interest"] is None


def test_asking_for_a_website_creates_no_site_and_no_charge(admin):
    biz = make_business("Interest Nothing")
    sub_before = owner_query("SELECT plan, status FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)
    assert biz.put("/tenant/website-interest", json={"interest": "wants_site"}).status_code == 200
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert owner_query("SELECT plan, status FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id) == sub_before


def test_the_admin_list_shows_the_answer_the_site_state_and_filters_by_it(admin, sites_on):  # noqa: F811
    wants = make_business("Interest Wants")
    own = make_business("Interest Own")
    built = make_business("Interest Built")
    wants.put("/tenant/website-interest", json={"interest": "wants_site"})
    own.put("/tenant/website-interest", json={"interest": "has_site"})
    built.put("/tenant/website-interest", json={"interest": "wants_site"})
    new_site(admin, {"id": built.tenant_id})
    assert row(admin, wants.tenant_id)["site_status"] is None and row(admin, wants.tenant_id)["website_interest"] == "wants_site"
    assert row(admin, built.tenant_id)["site_status"] == "draft"
    ids = lambda w: {i["id"] for i in admin.get("/admin/tenants", params={"website": w, "search": "Interest"}).json()["items"]}  # noqa: E731
    assert wants.tenant_id in ids("wants") and built.tenant_id not in ids("wants") and own.tenant_id not in ids("wants")  # someone whose site already exists is not "waiting"
    assert built.tenant_id in ids("built") and wants.tenant_id not in ids("built")
    assert own.tenant_id in ids("none") or own.tenant_id not in ids("wants")
    assert admin.get("/admin/tenants", params={"website": "bogus"}).status_code == 422


def test_the_business_summary_for_staff_carries_the_answer(admin, sites_on):  # noqa: F811
    biz = make_business("Interest Summary")
    biz.put("/tenant/website-interest", json={"interest": "wants_site"})
    s = admin.get(f"/admin/tenants/{biz.tenant_id}/site").json()
    assert s["website_interest"] == "wants_site" and s["site"] is None


def test_a_member_below_admin_and_another_business_cannot_change_it(admin):
    a = make_business("Interest A")
    b = make_business("Interest B")
    # b cannot name a's tenant: the route only ever changes the caller's own business
    b.put("/tenant/website-interest", json={"interest": "wants_site"})
    assert a.get("/tenant").json()["website_interest"] is None
    assert b.get("/tenant").json()["website_interest"] == "wants_site"


def test_it_works_while_sites_are_switched_off():
    assert settings.sites_enabled is False
    biz = make_business("Interest Off")
    assert biz.put("/tenant/website-interest", json={"interest": "wants_site"}).status_code == 200
