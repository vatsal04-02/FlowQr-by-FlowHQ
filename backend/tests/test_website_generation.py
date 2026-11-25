"""AI website generation from onboarding, on top of the existing website builder.

MOCKED: the AI is `Scripted` and Google is the test double. The database, row-level security, the job lifecycle, and the builder's own validator and renderer are real. A pass proves FlowQR's
logic; it is NOT evidence of how a real model writes or how Google answers."""
import json
import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models.base import utcnow
from app.services.ai.base import AIUnavailable
from app.services.sites import generator as gen
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_agent import Scripted
from tests.test_gbp import FakeGbpProvider, gid  # noqa: F401
from tests.test_google_and_reviews import connected, fake  # noqa: F401
from tests.test_location_permissions import invite

KB = {"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy"], "offers": [], "faqs": [], "prohibited_claims": []}
PLAN = json.dumps({"template": "clinic", "accent": "teal", "audience": "People in Lucknow with back or neck pain."})
COPY = json.dumps({"eyebrow": "Appointments", "headline": "Physiotherapy for back and neck pain in Lucknow", "subheading": "Calm, clear care close to home.", "about_heading": "About the clinic",
                   "about": "We help people with back and neck pain understand what is going on and move comfortably again.", "services_heading": "What we help with", "services_intro": "Tell us what hurts.",
                   "services": [{"title": "Back care", "description": "Assessment and a plan for an aching back."}, {"title": "Neck pain physiotherapy", "description": "Help with a stiff or painful neck."},
                                {"title": "Hair transplant", "description": "A service nobody offers here."}],
                   "contact_heading": "Book a visit", "contact_intro": "Send a message and we will call you back.", "seo_title": "Physiotherapy in Lucknow", "seo_description": "Back and neck pain physiotherapy in Lucknow."})


@pytest.fixture()
def on(monkeypatch):
    queued: list = []
    monkeypatch.setattr(settings, "sites_ai_builder_enabled", True)
    monkeypatch.setattr(gen, "enqueue", lambda job_id: queued.append(job_id))
    return queued


@pytest.fixture()
def biz(on):
    b = make_business("Gomti Physio")
    assert b.put("/agent/knowledge", json=KB).status_code == 200
    assert b.put("/tenant/website-interest", json={"interest": "wants_site"}).status_code == 200
    owner_exec("UPDATE tenants SET phone = '+91 98765 43210' WHERE id = :t", t=uuid.UUID(b.tenant_id))
    return b


def work(job_id, *outputs):
    p = Scripted(*(outputs or (PLAN, COPY)))
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    try:
        return gen.run(db, uuid.UUID(str(job_id)), provider=p), p
    finally:
        db.close()


def built(biz, *outputs):
    job = biz.post("/website/generate", json={}).json()["job"]
    status, p = work(job["id"], *outputs)
    return status, biz.get("/website").json(), p


def sec(state, typ):
    return next((s for s in state["site"]["sections"] if s["type"] == typ), None)


def test_with_the_switch_off_nothing_is_offered():
    b = make_business("Off Co")
    assert b.get("/website").json() == {"enabled": False}
    assert b.post("/website/generate", json={}).status_code == 404 and b.get("/website/preview").status_code == 404


def test_a_business_without_a_website_gets_a_draft_in_the_existing_builder_from_its_own_facts(biz, on):
    r = biz.post("/website/generate", json={})
    assert r.status_code == 200 and r.json()["created"] is True and r.json()["job"]["status"] == "queued" and len(on) == 1
    assert [s["status"] for s in r.json()["job"]["steps"]] == ["waiting"] * 12  # nothing is shown as done before work happens
    assert work(on[0])[0] == "completed"
    st = biz.get("/website").json()
    steps = {s["key"]: s for s in st["job"]["steps"]}
    assert st["job"]["status"] == "completed" and st["job"]["stage"] == "COMPLETED"
    assert steps["connect"]["status"] == "skipped" and steps["images"]["status"] == "skipped" and all(steps[k]["status"] == "done" for k in ("understand", "analyse", "structure", "content", "sections", "validate"))
    assert st["site"]["template"] == "clinic" and st["site"]["accent"] == "teal" and st["site"]["status"] == "draft"
    assert sec(st, "hero")["data"]["heading"].startswith("Physiotherapy for back")
    assert [i["title"] for i in sec(st, "services")["data"]["items"]] == ["Back care", "Neck pain physiotherapy"]  # the invented service never appears
    assert sec(st, "services")["enabled"] and sec(st, "contact")["enabled"] and sec(st, "disclaimer")["enabled"]
    for never in ("credentials", "gallery", "faqs", "trust"):
        assert sec(st, never) is None or sec(st, never)["enabled"] is False
    assert any("photos" in n.lower() for n in st["job"]["notes"])
    row = owner_query("SELECT commercial_status, status, published_content IS NULL FROM sites WHERE tenant_id = :t", t=uuid.UUID(biz.tenant_id))[0]
    assert tuple(row) == ("not_activated", "draft", True)
    page = biz.get("/website/preview")
    assert page.status_code == 200 and "Back care" in page.text and "noindex" in page.text and "Hair transplant" not in page.text and page.headers["cache-control"] == "no-store"


def test_claims_the_business_cannot_back_are_replaced_with_plain_wording(biz, on):
    bad = json.loads(COPY)
    bad["headline"] = "The best award winning clinic with 20 years of experience"
    bad["about"] = "We guarantee a complete cure. Rs 99 first visit."
    status, st, _ = built(biz, PLAN, json.dumps(bad))
    assert status == "completed"
    text = json.dumps(st["site"]["sections"]).lower()
    assert "award" not in text and "guarantee" not in text and "years of experience" not in text and "rs 99" not in text
    assert sec(st, "hero")["data"]["heading"] == "Gomti Physio" and any("replaced with plain wording" in n for n in st["job"]["notes"])


def test_when_the_ai_cannot_run_the_job_says_so_and_can_be_retried(biz, on):
    class Down(Scripted):
        def generate(self, system, user, **kw):
            raise AIUnavailable("x", code="credits")

    job = biz.post("/website/generate", json={}).json()["job"]
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert gen.run(db, uuid.UUID(job["id"]), provider=Down("x")) == "failed"
    db.close()
    j = biz.get("/website").json()["job"]
    assert j["status"] == "failed" and "no credit" in j["error"] and next(s for s in j["steps"] if s["key"] == "analyse")["status"] == "failed"
    assert next(s for s in j["steps"] if s["key"] == "content")["status"] == "waiting" and biz.get("/website").json()["site"] is None
    again = biz.post("/website/generate", json={}).json()
    assert again["created"] is True and again["job"]["id"] != job["id"] and work(again["job"]["id"])[0] == "completed"


def test_asking_twice_or_refreshing_never_makes_a_second_job_or_site(biz, on):
    a = biz.post("/website/generate", json={}).json()
    b = biz.post("/website/generate", json={}).json()
    assert b["created"] is False and b["job"]["id"] == a["job"]["id"] and len(on) == 1
    work(a["job"]["id"])
    c = biz.post("/website/generate", json={}).json()
    assert c["created"] is False and c["job"]["status"] == "completed"
    assert work(a["job"]["id"])[0] == "skipped"  # a duplicate delivery does nothing
    t = uuid.UUID(biz.tenant_id)
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=t)[0][0] == 1 and owner_query("SELECT count(*) FROM site_generation_jobs WHERE tenant_id = :t", t=t)[0][0] == 1


def test_a_job_whose_worker_died_is_reported_as_stopped_not_left_spinning(biz, on):
    job = biz.post("/website/generate", json={}).json()["job"]
    owner_exec("UPDATE site_generation_jobs SET status = 'running', updated_at = :u WHERE id = :j", u=utcnow() - timedelta(minutes=20), j=uuid.UUID(job["id"]))
    j = biz.get("/website").json()["job"]
    assert j["status"] == "failed" and "stopped before finishing" in j["error"]


def test_a_business_with_its_own_website_is_never_generated_for(biz, on):
    assert biz.put("/tenant/website-interest", json={"interest": "has_site"}).status_code == 200
    assert biz.post("/website/generate", json={}).status_code == 409 and on == []


def test_connecting_google_starts_it_once_and_only_for_a_business_with_no_website(on, connected, gid):  # noqa: F811
    t = uuid.UUID(connected.tenant_id)
    sel = {"selections": [{"google_location_id": gid, "selected": True, "location_id": connected.location_id}]}
    put = lambda: connected.http.put(f"/api/v1/google/connections/{connected.conn_id}/selection", json=sel, headers={"X-CSRF-Token": connected.csrf})  # noqa: E731
    assert put().status_code == 200 and on == []  # no answer to "do you have a website" yet: nothing starts
    connected.put("/tenant/website-interest", json={"interest": "wants_site"})
    assert put().status_code == 200 and len(on) == 1
    assert owner_query("SELECT trigger FROM site_generation_jobs WHERE tenant_id = :t", t=t)[0][0] == "google_connected"
    assert put().status_code == 200 and len(on) == 1  # reconnecting does not repeat it


def test_google_facts_are_used_when_connected(on, connected, gid, monkeypatch):  # noqa: F811
    from app.services import google as g

    provider = FakeGbpProvider()
    provider.details.update({"services": ["Dry needling", "job_type_id:internal"], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}], "phone": "+91 91111 22222"})
    monkeypatch.setattr(g, "get_google_provider", lambda: provider)
    connected.put("/tenant/website-interest", json={"interest": "wants_site"})
    connected.put("/agent/knowledge", json=KB)
    sel = {"selections": [{"google_location_id": gid, "selected": True, "location_id": connected.location_id}]}
    connected.http.put(f"/api/v1/google/connections/{connected.conn_id}/selection", json=sel, headers={"X-CSRF-Token": connected.csrf})
    assert work(on[0])[0] == "completed"
    st = connected.get("/website").json()
    assert next(s for s in st["job"]["steps"] if s["key"] == "connect")["status"] == "done"
    titles = [i["title"] for i in sec(st, "services")["data"]["items"]]
    assert "Dry needling" in titles and not any(":" in x for x in titles) and sec(st, "hours")["enabled"]


def test_only_this_business_and_only_its_admins(biz, on):
    built(biz)
    other = make_business("Other Clinic")
    assert other.get("/website").json()["site"] is None and other.get("/website/preview").status_code == 404
    staff = invite(biz, "staff")
    assert staff.post("/website/generate", json={}).status_code == 403 and staff.post("/website/ask", json={"instruction": "change colour"}).status_code == 403
    admin = invite(biz, "admin")
    assert admin.post("/website/publish", json={}).status_code == 403  # publishing is the owner's decision


def test_the_owner_edits_one_section_and_nothing_else_changes(biz, on):
    _, st, _ = built(biz)
    before = {s["id"]: s for s in st["site"]["sections"]}
    hero = sec(st, "hero")
    r = biz.put(f"/website/sections/{hero['id']}", json={"enabled": True, "data": {**hero["data"], "heading": "Back pain help in Gomti Nagar"}})
    assert r.status_code == 200 and sec(r.json(), "hero")["data"]["heading"] == "Back pain help in Gomti Nagar"
    assert all(s == before[s["id"]] for s in r.json()["site"]["sections"] if s["id"] != hero["id"])
    assert biz.put(f"/website/sections/{hero['id']}", json={"enabled": True, "data": {**hero["data"], "script": "<x>"}}).status_code == 422
    assert biz.post("/website/design", json={"accent": "navy"}).json()["site"]["accent"] == "navy"
    assert biz.post("/website/design", json={"accent": "gold"}).status_code == 422


def test_ai_edits_are_limited_checked_and_stay_inside_the_chosen_section(biz, on, monkeypatch):
    _, st, _ = built(biz)
    hero, about = sec(st, "hero"), sec(st, "about")
    answer = json.dumps({"changes": [{"op": "set_text", "section_id": hero["id"], "field": "heading", "value": "Move without back pain"},
                                     {"op": "set_text", "section_id": about["id"], "field": "body", "value": "Changed elsewhere."},
                                     {"op": "set_text", "section_id": hero["id"], "field": "subheading", "value": "The best award winning care, guaranteed."}], "cannot": ""})
    monkeypatch.setattr("app.api.v1.website.get_provider", lambda: Scripted(answer))
    r = biz.post("/website/ask", json={"instruction": "improve the headline", "section_id": hero["id"]})
    assert r.status_code == 200, r.text
    after = r.json()["state"]
    assert sec(after, "hero")["data"]["heading"] == "Move without back pain" and sec(after, "about")["data"]["body"] == about["data"]["body"]
    assert "award" not in sec(after, "hero")["data"]["subheading"].lower() and len(r.json()["refused"]) == 2


def test_publishing_needs_the_owner_and_stays_closed_until_hosting_and_the_add_on_exist(biz, on, monkeypatch):
    built(biz)
    r = biz.post("/website/publish", json={})
    assert r.status_code == 200 and r.json()["published"] is False and "Nothing is public" in r.json()["message"]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'site.publish_requested'", t=uuid.UUID(biz.tenant_id))[0][0] == 1
    monkeypatch.setattr(settings, "sites_enabled", True)
    r = biz.post("/website/publish", json={}).json()
    assert r["published"] is False and "not activated" in r["message"]
    assert owner_query("SELECT status, published_content IS NULL FROM sites WHERE tenant_id = :t", t=uuid.UUID(biz.tenant_id))[0] == ("draft", True)


def test_the_new_job_table_is_isolated_by_row_level_security():
    row = owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'site_generation_jobs'")[0]
    assert tuple(row) == (True, True)
