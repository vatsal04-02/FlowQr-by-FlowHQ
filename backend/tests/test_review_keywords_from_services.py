"""The keywords (chips) on a business's review page come from the business's OWN list of services/products, plus Staff and Value for money; with no services they are the category's standard
list, exactly as before. Staff can set the services when they add a business, and the owner's own knowledge page drives the same list. The AI is a labelled test double."""
import uuid

import pytest

from app.core.config import settings
from app.models import Tenant
from app.services.review_suggestions import all_topics, merged_context, service_topic
from tests.conftest import make_business, owner_query
from tests.test_review_growth import UA, campaign, llm, pub  # noqa: F401

WATCH = ["Watch repair", "Battery change", "Strap replacement"]


def payload(**kw):
    n = uuid.uuid4().hex[:6]
    base = {"name": f"Royal Watch {n}", "category": "Electronics or mobile", "phone": f"98{uuid.uuid4().int % 10**8:08d}", "city": "Kanpur", "review_url": f"https://g.page/r/Rw{n}Ab12/review"}
    base.update(kw)
    return base


def labels(page) -> list[str]:
    return [s["en"] for s in page["suggestions"]]


def test_a_business_with_services_gets_its_own_keywords_then_staff_and_value():
    t = Tenant(name="Royal Watch", category="Electronics or mobile", review_context={"services": WATCH})
    assert [x.en for x in merged_context(t).topics] == [*WATCH, "Staff", "Value for money"]
    ids = [x.id for x in merged_context(t).topics]
    assert ids[0] == service_topic("watch repair").id == service_topic("  Watch Repair ").id  # stable, whatever the capitalisation or spacing


def test_without_services_the_category_list_is_unchanged():
    t = Tenant(name="Any", category="Dental clinic", review_context={})
    assert [x.id for x in merged_context(t).topics] == [x.id for x in all_topics({}, "dental")]
    assert "Staff" in [x.en for x in merged_context(t).topics] and len(merged_context(t).topics) >= 5
    off = Tenant(name="Any", category="Dental clinic", review_context={"services": WATCH, "chips_from_services": False})
    assert "Watch repair" not in [x.en for x in merged_context(off).topics]  # the owner can keep the standard list


def test_only_the_first_six_services_become_keywords():
    t = Tenant(name="X", category="Other", review_context={"services": [f"Service number {i}" for i in range(10)]})
    topics = merged_context(t).topics
    assert len(topics) == 8 and topics[-2].en == "Staff" and topics[0].en == "Service number 0" and topics[5].en == "Service number 5"


def test_staff_set_the_services_when_adding_a_business_and_can_change_them_later(admin):
    r = admin.post("/admin/tenants", json=payload(services=WATCH))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    d = admin.get(f"/admin/tenants/{tid}").json()["tenant"]
    assert d["services"] == WATCH and d["review_keywords_source"] == "services"
    assert [k["label"] for k in d["review_keywords"]] == [*WATCH, "Staff", "Value for money"]
    r = admin.patch(f"/admin/tenants/{tid}", json={"services": ["Watch repair", "Glass replacement"]})
    assert r.status_code == 200 and [k["label"] for k in r.json()["review_keywords"]][:2] == ["Watch repair", "Glass replacement"]
    assert admin.patch(f"/admin/tenants/{tid}", json={"services": []}).json()["review_keywords_source"] == "category"  # emptied: back to the standard list
    audit = owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'admin.business_edit'", t=tid)
    assert audit and all("Glass" not in str(a[0]) for a in audit)  # the audit entry names the field, not the text


def test_claims_prices_and_links_are_refused_in_the_services_list(admin):
    for bad in ("Best watch repair in town", "Battery change for Rs 100", "Visit www.example.com"):
        assert admin.post("/admin/tenants", json=payload(services=[bad])).status_code == 422, bad


def test_the_public_review_page_shows_the_owners_services_and_a_picked_one_reaches_the_writer(biz_a, client, llm):
    assert biz_a.put("/review-growth/context", json={"description": "We repair and sell wrist watches.", "services": WATCH}).status_code == 200
    c = campaign(biz_a)
    page = pub(client, "GET", c["public_id"]).json()
    assert labels(page) == [*WATCH, "Staff", "Value for money"]
    pick = next(s["id"] for s in page["suggestions"] if s["en"] == "Watch repair")
    llm.texts = ["I appreciated the watch repair and was happy with it."]
    r = pub(client, "POST", c["public_id"], "/generate", json={"suggestions": [pick], "sentiment": "good", "language": "en", "rating": 5}).json()
    assert r.get("ai_status") == "ok", r
    assert "watch repair" in r["draft"].lower()
    sent = llm.calls[-1][1]
    assert "Watch repair" in sent  # the picked keyword is what the writer was told the customer chose to comment on


def test_owner_can_switch_a_service_keyword_off_and_back_to_the_standard_list(biz_a, client):
    ctx = biz_a.put("/review-growth/context", json={"services": WATCH}).json()
    assert ctx["chips_source"] == "services"
    battery = next(s["id"] for s in ctx["suggestions"] if s["en"] == "Battery change")
    ctx = biz_a.put("/review-growth/context", json={"services": WATCH, "disabled_suggestions": [battery]}).json()
    assert next(s for s in ctx["suggestions"] if s["id"] == battery)["enabled"] is False
    c = campaign(biz_a)
    assert "Battery change" not in labels(pub(client, "GET", c["public_id"]).json())
    ctx = biz_a.put("/review-growth/context", json={"services": WATCH, "chips_from_services": False}).json()
    assert ctx["chips_source"] == "category" and "Watch repair" not in [s["en"] for s in ctx["suggestions"]]


def test_the_owners_knowledge_page_drives_the_same_list(biz_a, client):
    k = biz_a.get("/agent/knowledge").json()
    body = {key: k[key] for key in ("description", "services", "offers", "hours", "faqs", "brand_voice", "approved_claims", "prohibited_claims")}
    body["services"] = ["Watch repair", "Dial polishing"]
    assert biz_a.put("/agent/knowledge", json=body).status_code == 200
    assert labels(pub(client, "GET", campaign(biz_a)["public_id"]).json())[:2] == ["Watch repair", "Dial polishing"]
