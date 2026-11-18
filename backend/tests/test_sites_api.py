"""Website builder through the API: administrator-managed, feature-flagged, tenant-isolated, audited.

Covers: the feature flag; admin authorisation; creation and the commercial rules; tenant isolation (images, enquiries, row-level security); drafts never public; publish, unpublish, failure,
retry and rollback; suspension; commercial status, grace and lapse; site-name quarantine; images; enquiries (token, honeypot, consent, rate limit, retention); export and deletion; cookie isolation."""
import io
import uuid
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.core.config import config_problems, settings
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import account as account_svc
from app.services.sites import hosting
from app.services.sites import service as svc
from app.services.sites.hosting import HostingError, LocalDirectoryProvider
from tests.conftest import make_business, make_user, owner_exec, owner_query
from tests.test_admin_businesses import create
from tests.test_config_guard import good
from tests.test_sites_content import complete
from tests.test_sites_media import jpeg, png

TOKEN = "T" * 40
BASE = "flowqr.site"
REASON = "Pilot customer, no charge for the trial"


@pytest.fixture()
def sites_on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sites_enabled", True)
    monkeypatch.setattr(settings, "sites_base_domain", BASE)
    monkeypatch.setattr(settings, "sites_service_token", TOKEN)
    p = LocalDirectoryProvider(tmp_path)
    hosting.set_provider(p)
    yield p
    hosting.set_provider(None)


def new_site(admin, biz, **kw):
    body = {"commercial_status": "complimentary", "commercial_reason": REASON}
    body.update(kw)
    r = admin.post(f"/admin/tenants/{biz['id']}/site", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def save(admin, site, content=None, expect=200):
    r = admin.put(f"/admin/sites/{site['id']}/content", json={"content": content if content is not None else site["draft_content"], "base_version": site["draft_version"]})
    assert r.status_code == expect, r.text
    return r.json()


def ready(admin, site):
    """Fill the draft in so it can be published, and save it."""
    return save(admin, site, complete(site["draft_content"], site["template_key"]))


def publish(admin, site, expect=200):
    r = admin.post(f"/admin/sites/{site['id']}/publish", json={})
    assert r.status_code == expect, r.text
    return r.json()


def live_site(admin, **biz_kw):
    biz = create(admin, **biz_kw)
    s = ready(admin, new_site(admin, biz))
    return biz, publish(admin, s)


def anon():
    return TestClient(app, base_url="http://testserver")


def enquire(host, token=TOKEN, **over):
    body = {"host": host, "name": "Asha Verma", "phone": "98765 43210", "email": "", "message": "Do you have a slot on Friday?", "consent": True, "website": "", "client_ip": "203.0.113.7"}
    body.update(over)
    return anon().post("/api/v1/site-enquiry", json=body, headers={"X-Sites-Token": token} if token else {})


def audit_actions(tenant_id):
    return [r[0] for r in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t ORDER BY created_at", t=tenant_id)]


# ================================================================================================================ 1. the feature flag
def test_everything_is_off_by_default_and_the_rest_of_the_app_is_unaffected(admin, biz_a):
    assert settings.sites_enabled is False
    assert admin.get("/admin/sites/config").json()["enabled"] is False
    assert admin.get("/admin/sites/templates").status_code == 200  # the catalogue is static data
    biz = create(admin)
    r = admin.get(f"/admin/tenants/{biz['id']}/site")
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["site"] is None
    r = admin.post(f"/admin/tenants/{biz['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sites_disabled"
    assert admin.get(f"/admin/sites/{uuid.uuid4()}").status_code == 409
    assert enquire("x.flowqr.site").status_code == 404
    assert admin.get("/admin/tenants").status_code == 200 and biz_a.get("/tenant").status_code == 200  # nothing else changed
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=biz["id"])[0][0] == 0


def test_the_housekeeping_job_does_nothing_while_sites_are_off():
    from app.workers.tasks import sites_housekeeping

    assert sites_housekeeping() == {"enabled": False}


# ================================================================================================================ 2. who may call what
ROUTES = [("get", "/admin/tenants/{t}/site", None), ("post", "/admin/tenants/{t}/site", {"commercial_status": "complimentary", "commercial_reason": REASON}), ("get", "/admin/sites/{s}", None),
          ("put", "/admin/sites/{s}/content", {"content": {}, "base_version": 1}), ("post", "/admin/sites/{s}/template", {"template_key": "salon"}), ("post", "/admin/sites/{s}/slug", {"site_slug": "newname"}),
          ("post", "/admin/sites/{s}/assets", None), ("get", "/admin/sites/{s}/preview", None), ("post", "/admin/sites/{s}/publish", {}), ("post", "/admin/sites/{s}/unpublish", None),
          ("post", "/admin/sites/{s}/suspend", {"reason": "abuse report"}), ("post", "/admin/sites/{s}/unsuspend", None), ("post", "/admin/sites/{s}/rollback", {"revision": 1}),
          ("post", "/admin/sites/{s}/commercial", {"status": "expired", "reason": "not renewed"}), ("delete", "/admin/sites/{s}", None), ("get", "/admin/sites/{s}/enquiries", None),
          ("get", "/admin/sites/{s}/enquiries.csv", None), ("get", "/admin/sites/config", None), ("get", "/admin/sites/templates", None), ("get", "/admin/sites/slug-check?slug=abc", None)]


def test_every_website_admin_route_is_closed_to_anonymous_callers_and_to_every_business(admin, biz_a, biz_b, sites_on):
    biz, s = create(admin), None
    s = new_site(admin, biz)
    for method, path, body in ROUTES:
        url = path.format(t=biz["id"], s=s["id"])
        kw = {"json": body} if body is not None else {}
        assert anon().request(method.upper(), "/api/v1" + url, **kw).status_code in (401, 403), (method, path)
        for who in (biz_a, biz_b):
            assert getattr(who, method)(url, **kw).status_code == 403, (method, path)
    assert owner_query("SELECT status, draft_version FROM sites WHERE id = :s", s=s["id"])[0] == ("draft", 1)  # nothing was changed by a refused caller


def test_a_business_owner_cannot_reach_any_website_of_another_business_either(admin, biz_a, sites_on):
    s = new_site(admin, create(admin))
    assert biz_a.get(f"/admin/sites/{s['id']}").status_code == 403 and biz_a.get(f"/admin/sites/{s['id']}/preview").status_code == 403


# ================================================================================================================ 3. creating a website
def test_a_website_is_created_for_a_business_with_no_login_and_prefilled_from_its_record(admin, sites_on):
    before = owner_query("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM memberships)")[0]
    biz = create(admin, name="Sharma Physio Clinic", category="Physiotherapy clinic", city="Kanpur", address="12 Mall Road", review_url="https://g.page/r/ShrmaPhysio1/review")
    s = new_site(admin, biz)
    assert owner_query("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM memberships)")[0] == (before[0], before[1])  # no account was created for the shopkeeper
    c = s["draft_content"]
    assert s["template_key"] == "clinic" and s["status"] == "draft" and s["draft_version"] == 1 and s["live_version"] == 0
    assert s["site_slug"].startswith("sharma-physio-clinic") and s["hostname"] == f"{s['site_slug']}.{BASE}" and s["url"] == f"https://{s['hostname']}/"
    assert c["business"]["name"] == "Sharma Physio Clinic" and c["business"]["phone"].startswith("+91 98") and c["business"]["city"] == "Kanpur" and "12 Mall Road" in c["business"]["address"]
    assert c["business"]["review_url"] == "https://g.page/r/ShrmaPhysio1/review" and c["sections"][0]["data"]["heading"] == "Sharma Physio Clinic"
    assert [d["hostname"] for d in s["domains"]] == [s["hostname"]] and s["domains"][0]["is_primary"] and s["domains"][0]["status"] == "active"
    assert "admin.site_create" in audit_actions(biz["id"])


def test_hosting_is_never_silently_free(admin, sites_on):
    biz = create(admin)
    url = f"/admin/tenants/{biz['id']}/site"
    assert admin.post(url, json={}).status_code == 422  # the commercial status is required
    r = admin.post(url, json={"commercial_status": "complimentary"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    assert admin.post(url, json={"commercial_status": "complimentary", "commercial_reason": "ok"}).status_code == 422  # too short to be a reason
    assert admin.post(url, json={"commercial_status": "paid_offline"}).json()["detail"]["code"] == "payment_details_required"
    assert admin.post(url, json={"commercial_status": "paid_offline", "billing_period": "monthly"}).status_code == 422
    for bad in ("expired", "suspended", "free", "trial"):
        assert admin.post(url, json={"commercial_status": bad, "commercial_reason": REASON}).status_code in (409, 422)
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=biz["id"])[0][0] == 0
    r = admin.post(url, json={"commercial_status": "paid_offline", "billing_period": "annual", "paid_until": (utcnow() + timedelta(days=365)).date().isoformat()})
    assert r.status_code == 201 and r.json()["commercial"]["status"] == "paid_offline" and r.json()["commercial"]["billing_period"] == "annual"


def test_one_website_per_business_and_not_for_a_suspended_business(admin, sites_on):
    biz = create(admin)
    new_site(admin, biz)
    r = admin.post(f"/admin/tenants/{biz['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_exists"
    other = create(admin)
    assert admin.post(f"/admin/tenants/{other['id']}/suspend", json={"reason": "non-payment of the card fee"}).status_code == 204
    r = admin.post(f"/admin/tenants/{other['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "tenant_suspended"
    assert admin.post(f"/admin/tenants/{uuid.uuid4()}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON}).status_code == 404


def test_a_website_can_also_be_made_for_a_business_that_has_its_own_login(admin, biz_a, sites_on):
    s = new_site(admin, {"id": biz_a.tenant_id})
    assert s["tenant_id"] == biz_a.tenant_id and s["draft_content"]["business"]["name"] == "Alpha Physio"


def test_site_names_reserved_duplicate_and_malformed(admin, sites_on):
    b1, b2 = create(admin), create(admin)
    for bad in ("www", "api", "admin", "go", "ab", "Sharma", "-x-", "a--b", "xn--abc", "a.b", "../x", "x" * 41):
        r = admin.post(f"/admin/tenants/{b1['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON, "site_slug": bad})
        assert r.status_code in (409, 422), bad
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=b1["id"])[0][0] == 0
    slug = f"royal-salon-{uuid.uuid4().hex[:6]}"
    assert new_site(admin, b1, site_slug=slug)["site_slug"] == slug
    r = admin.post(f"/admin/tenants/{b2['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON, "site_slug": slug})
    assert r.status_code == 409 and "already used" in r.json()["detail"]["message"]
    chk = admin.get("/admin/sites/slug-check", params={"slug": slug}).json()
    assert chk["available"] is False and admin.get("/admin/sites/slug-check", params={"slug": "www"}).json()["problem"] == "That name is reserved."
    assert admin.get("/admin/sites/slug-check", params={"slug": f"free-{uuid.uuid4().hex[:8]}"}).json()["available"] is True


# ================================================================================================================ 4. tenant isolation
def test_one_businesss_images_cannot_be_used_or_read_through_another_site(admin, sites_on):
    a, b = new_site(admin, create(admin)), new_site(admin, create(admin))
    img = admin.post(f"/admin/sites/{a['id']}/assets", content=jpeg(), headers={"Content-Type": "image/jpeg"}, params={"alt_text": "Reception"})
    assert img.status_code == 201
    aid = img.json()["id"]
    # B tries to use A's image in its content
    c = b["draft_content"]
    c["sections"][0]["data"]["image"] = aid
    r = admin.put(f"/admin/sites/{b['id']}/content", json={"content": c, "base_version": b["draft_version"]})
    assert r.status_code == 422 and any("does not belong" in e["message"] for e in r.json()["detail"]["errors"])
    # and cannot fetch, edit or delete it through its own site id
    assert admin.get(f"/admin/sites/{b['id']}/assets/{aid}/file").status_code == 404
    assert admin.patch(f"/admin/sites/{b['id']}/assets/{aid}", json={"alt_text": "stolen"}).status_code == 404
    assert admin.delete(f"/admin/sites/{b['id']}/assets/{aid}").status_code == 404
    assert admin.get(f"/admin/sites/{a['id']}/assets/{aid}/file").status_code == 200
    assert owner_query("SELECT alt_text FROM site_assets WHERE id = :a", a=aid)[0][0] == "Reception"


def test_row_level_security_shows_a_business_only_its_own_website_rows(admin, sites_on):
    a, b = create(admin), create(admin)
    sa, sb = new_site(admin, a), new_site(admin, b)
    admin.post(f"/admin/sites/{sa['id']}/assets", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    publish(admin, ready(admin, sa))
    enquire(sa["hostname"])
    for table in ("sites", "site_domains", "site_assets", "site_enquiries", "site_revisions"):
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=uuid.UUID(b["id"]))
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id <> :t"), {"t": b["id"]}).scalar() == 0, table
            mine = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=uuid.UUID(a["id"]))
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": b["id"]}).scalar() == 0, table
        assert mine == (1 if table in ("sites", "site_domains") else 0), table
    with SessionLocal() as db:  # no tenant at all: nothing
        set_rls_context(db)
        assert db.execute(text("SELECT count(*) FROM sites")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM site_slug_quarantine")).scalar() == 0
    assert sb["tenant_id"] == b["id"]


def test_the_slug_quarantine_is_platform_only_and_revisions_are_append_only():
    app_role = settings.database_url.split("//")[1].split(":")[0]
    assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'site_slug_quarantine'")[0][0] is True
    assert "bypass_rls" in owner_query("SELECT qual FROM pg_policies WHERE tablename = 'site_slug_quarantine'")[0][0]
    for priv in ("UPDATE", "DELETE", "TRUNCATE"):
        assert owner_query("SELECT has_table_privilege(:r, 'public.site_revisions', :p)", r=app_role, p=priv)[0][0] is False, priv
    assert owner_query("SELECT has_table_privilege(:r, 'public.site_revisions', 'INSERT')", r=app_role)[0][0] is True


def test_the_database_allows_only_one_active_primary_hostname_per_site_and_lower_case_names(admin, sites_on):
    s = new_site(admin, create(admin))
    with pytest.raises(Exception):
        owner_exec("INSERT INTO site_domains (id, site_id, tenant_id, hostname, domain_type, status, is_primary) VALUES (gen_random_uuid(), :s, :t, :h, 'custom', 'active', true)",
                   s=s["id"], t=s["tenant_id"], h=f"second-{uuid.uuid4().hex[:6]}.example.com")
    with pytest.raises(Exception):
        owner_exec("INSERT INTO site_domains (id, site_id, tenant_id, hostname, domain_type, status, is_primary) VALUES (gen_random_uuid(), :s, :t, 'MixedCase.Example.com', 'custom', 'pending', false)", s=s["id"], t=s["tenant_id"])
    with pytest.raises(Exception):
        owner_exec("INSERT INTO site_domains (id, site_id, tenant_id, hostname, domain_type, status, is_primary) VALUES (gen_random_uuid(), :s, :t, :h, 'custom', 'pending', false)", s=s["id"], t=s["tenant_id"], h=s["hostname"])


# ================================================================================================================ 5. saving, previewing, publishing
def test_saving_needs_the_version_the_editor_started_from(admin, sites_on):
    s = new_site(admin, create(admin))
    c = s["draft_content"]
    c["business"]["tagline"] = "First edit"
    s2 = save(admin, s, c)
    assert s2["draft_version"] == 2 and s2["draft_content"]["business"]["tagline"] == "First edit"
    c["business"]["tagline"] = "A second editor with a stale page"
    r = admin.put(f"/admin/sites/{s['id']}/content", json={"content": c, "base_version": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict" and r.json()["detail"]["current_version"] == 2
    assert owner_query("SELECT draft_content->'business'->>'tagline' FROM sites WHERE id = :s", s=s["id"])[0][0] == "First edit"


def test_invalid_content_is_refused_with_the_path_of_every_problem(admin, sites_on):
    s = new_site(admin, create(admin))
    c = s["draft_content"]
    c["business"]["maps_url"] = "https://evil.example/x"
    c["business"]["email"] = "nope"
    c["sections"][0]["data"]["evil"] = "x"
    r = admin.put(f"/admin/sites/{s['id']}/content", json={"content": c, "base_version": 1})
    assert r.status_code == 422
    assert {"business.maps_url", "business.email", "sections[0].data.evil"} <= {e["path"] for e in r.json()["detail"]["errors"]}
    assert owner_query("SELECT draft_version FROM sites WHERE id = :s", s=s["id"])[0][0] == 1


def test_markup_in_a_draft_is_shown_as_text_in_the_preview(admin, sites_on):
    s = new_site(admin, create(admin))
    c = s["draft_content"]
    c["sections"][0]["data"]["subheading"] = '<img src=x onerror=alert(1)><script>alert(2)</script>'
    s = save(admin, s, c)
    r = admin.get(f"/admin/sites/{s['id']}/preview")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "noindex" in r.headers["x-robots-tag"] and r.headers["cache-control"] == "no-store"
    assert "<img src=x" not in r.text and "<script>alert" not in r.text and "&lt;img src=x onerror=alert(1)&gt;" in r.text and "Preview. This page is not published." in r.text


def test_a_draft_is_never_public_and_unfinished_content_cannot_be_published(admin, sites_on):
    biz = create(admin)
    s = new_site(admin, biz)
    assert sites_on.read(s["hostname"]) is None
    r = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_ready" and len(r.json()["detail"]["blockers"]) >= 3
    assert sites_on.read(s["hostname"]) is None and owner_query("SELECT status, live_version FROM sites WHERE id = :s", s=s["id"])[0] == ("draft", 0)
    assert s["template_key"] == "restaurant"  # a sweet shop is suggested the restaurant template
    assert s["readiness"] and any("Menu" in b["message"] for b in s["readiness"]) and any("turn the section off" in b["message"] for b in s["readiness"])


def test_publish_puts_the_validated_snapshot_live_and_later_edits_stay_private(admin, sites_on):
    biz = create(admin)
    s = ready(admin, new_site(admin, biz))
    p = publish(admin, s)
    assert p["status"] == "published" and p["live_version"] == 1 and p["publish_state"] == "idle" and p["published_at"] and p["revisions"][0]["revision"] == 1
    html = sites_on.read(s["hostname"]).decode()
    assert "<h1>" in html and biz["name"] in html and 'rel="canonical" href="https://' + s["hostname"] + '/"' in html and "<script>" not in html.replace('<script type="application/ld+json">', "")
    assert sites_on.read(s["hostname"], "privacy/index.html") and sites_on.read(s["hostname"], "robots.txt") and sites_on.read(s["hostname"], "sitemap.xml")
    # an edit that is not published is not visible
    c = p["draft_content"]
    c["sections"][0]["data"]["heading"] = "WORK IN PROGRESS HEADING"
    save(admin, p, c)
    assert b"WORK IN PROGRESS HEADING" not in sites_on.read(s["hostname"])
    assert "WORK IN PROGRESS HEADING" in admin.get(f"/admin/sites/{s['id']}/preview").text
    acts = audit_actions(biz["id"])
    assert "admin.site_publish" in acts and "admin.site_edit" in acts


def test_unpublish_takes_the_site_offline_and_publish_brings_it_back(admin, sites_on):
    biz, s = live_site(admin)
    assert sites_on.read(s["hostname"])
    u = admin.post(f"/admin/sites/{s['id']}/unpublish")
    assert u.status_code == 200 and u.json()["status"] == "unpublished" and sites_on.read(s["hostname"]) is None and sites_on.resolve_site_hostname(s["hostname"]) is None
    assert admin.post(f"/admin/sites/{s['id']}/unpublish").status_code == 409  # already offline
    again = publish(admin, u.json())
    assert again["status"] == "published" and again["live_version"] == 2 and sites_on.read(s["hostname"])
    assert "admin.site_unpublish" in audit_actions(biz["id"])


def test_a_failed_publish_leaves_the_live_site_alone_and_can_be_retried(admin, sites_on):
    biz, s = live_site(admin)
    old = sites_on.read(s["hostname"])
    c = s["draft_content"]
    c["sections"][0]["data"]["heading"] = "The new heading"
    s = save(admin, s, c)
    sites_on.fail_after = 2
    r = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "publish_failed" and r.json()["detail"]["retryable"] is True and "already live is unchanged" in r.json()["detail"]["message"]
    assert sites_on.read(s["hostname"]) == old, "a failed publish changed the live website"
    row = owner_query("SELECT status, live_version, publish_state, publish_error, publish_counter FROM sites WHERE id = :s", s=s["id"])[0]
    assert row[0] == "published" and row[1] == 1 and row[2] == "failed" and row[3] and row[4] == 2
    assert "admin.site_publish_failed" in audit_actions(biz["id"])
    # nothing about the failure reveals a secret or a path
    assert "/tmp" not in row[3] and "Traceback" not in row[3]
    sites_on.fail_after = None
    ok = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert ok.status_code == 200 and ok.json()["live_version"] == 3 and ok.json()["publish_state"] == "idle" and ok.json()["publish_error"] is None
    assert b"The new heading" in sites_on.read(s["hostname"])


def test_hosting_that_is_not_configured_is_reported_not_guessed(admin, sites_on, monkeypatch):
    s = ready(admin, new_site(admin, create(admin)))
    hosting.set_provider(hosting.CloudflareProvider(account_id="", api_token="", kv_namespace_id="", bucket="", access_key_id="", secret_access_key=""))
    r = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hosting_not_configured"


def test_rollback_publishes_an_earlier_revision_as_a_new_one(admin, sites_on):
    biz, s = live_site(admin)
    host = s["hostname"]
    v1 = sites_on.read(host)
    c = s["draft_content"]
    c["sections"][0]["data"]["heading"] = "Second version heading"
    publish(admin, save(admin, s, c))
    assert b"Second version heading" in sites_on.read(host)
    r = admin.post(f"/admin/sites/{s['id']}/rollback", json={"revision": 1})
    assert r.status_code == 200
    out = r.json()
    assert sites_on.read(host) == v1 and out["live_version"] == 3 and [x["revision"] for x in out["revisions"]] == [3, 2, 1] and out["revisions"][0]["note"] == "Rollback to revision 1"
    assert out["draft_content"]["sections"][0]["data"]["heading"] != "Second version heading"
    assert admin.post(f"/admin/sites/{s['id']}/rollback", json={"revision": 99}).status_code == 404
    assert "admin.site_rollback" in audit_actions(biz["id"])


def test_the_revision_history_cannot_be_edited_or_deleted_by_the_application(admin, sites_on):
    _, s = live_site(admin)
    app_role = settings.database_url.split("//")[1].split(":")[0]
    for priv in ("UPDATE", "DELETE", "TRUNCATE"):
        assert owner_query("SELECT has_table_privilege(:r, 'public.site_revisions', :p)", r=app_role, p=priv)[0][0] is False, priv
    assert owner_query("SELECT count(*) FROM site_revisions WHERE site_id = :s", s=s["id"])[0][0] == 1


# ================================================================================================================ 6. suspension
def test_suspending_hides_the_site_without_losing_anything_and_resuming_restores_it(admin, sites_on):
    biz, s = live_site(admin)
    assert admin.post(f"/admin/sites/{s['id']}/suspend", json={"reason": "no"}).status_code == 422  # a reason is required
    r = admin.post(f"/admin/sites/{s['id']}/suspend", json={"reason": "Reported for misleading claims"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert sites_on.read(s["hostname"]) is None and sites_on.resolve_site_hostname(s["hostname"])["status"] == "suspended"
    assert admin.post(f"/admin/sites/{s['id']}/publish", json={}).status_code == 422  # a suspended site cannot be published over
    assert owner_query("SELECT count(*) FROM site_revisions WHERE site_id = :s", s=s["id"])[0][0] == 1 and owner_query("SELECT draft_content IS NOT NULL FROM sites WHERE id = :s", s=s["id"])[0][0]
    u = admin.post(f"/admin/sites/{s['id']}/unsuspend")
    assert u.status_code == 200 and u.json()["status"] == "published" and sites_on.read(s["hostname"])
    assert admin.post(f"/admin/sites/{s['id']}/unsuspend").status_code == 409
    assert {"admin.site_suspend", "admin.site_unsuspend"} <= set(audit_actions(biz["id"]))


def test_a_site_that_was_never_published_stays_unpublished_when_it_is_resumed(admin, sites_on):
    s = new_site(admin, create(admin))
    admin.post(f"/admin/sites/{s['id']}/suspend", json={"reason": "Held while we check the business"})
    assert admin.post(f"/admin/sites/{s['id']}/unsuspend").json()["status"] == "unpublished"


def test_suspending_the_business_takes_its_website_out_of_view_and_it_cannot_be_resumed_meanwhile(admin, sites_on):
    biz, s = live_site(admin)
    assert admin.post(f"/admin/tenants/{biz['id']}/suspend", json={"reason": "non-payment of the card fee"}).status_code == 204
    assert sites_on.read(s["hostname"]) is None and owner_query("SELECT status FROM sites WHERE id = :s", s=s["id"])[0][0] == "suspended"
    assert enquire(s["hostname"]).status_code == 404
    r = admin.post(f"/admin/sites/{s['id']}/unsuspend")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "commercial_not_active"
    assert admin.post(f"/admin/tenants/{biz['id']}/unsuspend").status_code == 204
    assert admin.post(f"/admin/sites/{s['id']}/unsuspend").json()["status"] == "published" and sites_on.read(s["hostname"])


# ================================================================================================================ 7. commercial status, grace and lapse
def commercial(admin, s, **body):
    return admin.post(f"/admin/sites/{s['id']}/commercial", json=body)


def test_every_commercial_change_is_validated_and_audited_with_before_after_and_reason(admin, sites_on):
    biz, s = live_site(admin)
    assert commercial(admin, s, status="expired").status_code == 422 and commercial(admin, s, status="expired", reason="no").status_code == 422
    assert commercial(admin, s, status="paid_offline", billing_period="monthly").status_code == 422
    assert commercial(admin, s, status="free", reason="please").status_code == 422
    paid = (utcnow() + timedelta(days=30)).date().isoformat()
    r = commercial(admin, s, status="paid_offline", billing_period="monthly", paid_until=paid)
    assert r.status_code == 200 and r.json()["commercial"]["status"] == "paid_offline" and r.json()["commercial"]["paid_until"] == paid
    r = commercial(admin, s, status="expired", reason="Did not renew after the first month")
    assert r.json()["commercial"]["status"] == "expired" and r.json()["commercial"]["grace_until"] is not None
    rows = owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'admin.site_commercial' ORDER BY created_at", t=biz["id"])
    assert len(rows) == 2 and rows[0][0]["from"]["status"] == "complimentary" and rows[0][0]["to"] == "paid_offline" and rows[1][0]["from"]["status"] == "paid_offline" and rows[1][0]["to"] == "expired"
    assert rows[1][0]["reason"] == "Did not renew after the first month" and rows[1][0]["grace_until"]
    assert owner_query("SELECT user_id IS NOT NULL FROM audit_logs WHERE tenant_id = :t AND action = 'admin.site_commercial'", t=biz["id"])[0][0]


def test_an_expired_site_stays_up_during_the_grace_period_then_is_suspended_never_deleted(admin, sites_on):
    biz, s = live_site(admin)
    commercial(admin, s, status="expired", reason="Hosting not renewed")
    assert sites_on.read(s["hostname"]), "an expired site must stay up during the grace period"
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        out = svc.enforce_commercial(db, utcnow() + timedelta(days=settings.sites_grace_days - 1))
        db.commit()
    assert out["suspended"] == 0 and sites_on.read(s["hostname"])
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        out = svc.enforce_commercial(db, utcnow() + timedelta(days=settings.sites_grace_days + 1))
        db.commit()
    assert out["suspended"] >= 1 and sites_on.read(s["hostname"]) is None
    row = owner_query("SELECT status, draft_content IS NOT NULL, published_content IS NOT NULL FROM sites WHERE id = :s", s=s["id"])[0]
    assert row == ("suspended", True, True)  # nothing was deleted
    assert owner_query("SELECT count(*) FROM site_assets WHERE site_id = :s", s=s["id"])[0][0] == 0 and owner_query("SELECT count(*) FROM site_revisions WHERE site_id = :s", s=s["id"])[0][0] == 1
    assert "system.site_suspend" in audit_actions(biz["id"])
    # content is still there to export
    assert admin.get(f"/admin/sites/{s['id']}").json()["draft_content"]["business"]["name"] == biz["name"]


def test_a_paid_until_date_that_passes_starts_the_grace_period(admin, sites_on):
    biz = create(admin)
    s = new_site(admin, biz, commercial_status="paid_offline", commercial_reason=None, billing_period="monthly", paid_until=(utcnow() + timedelta(days=5)).date().isoformat())
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        out = svc.enforce_commercial(db, utcnow() + timedelta(days=6))
        db.commit()
    assert out["expired"] >= 1
    row = owner_query("SELECT commercial_status, grace_until IS NOT NULL FROM sites WHERE id = :s", s=s["id"])[0]
    assert row == ("expired", True) and "system.site_expired" in audit_actions(biz["id"])


def test_publishing_needs_an_active_commercial_status(admin, sites_on):
    biz = create(admin)
    s = ready(admin, new_site(admin, biz))
    commercial(admin, s, status="expired", reason="Hosting not renewed")
    r = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert r.status_code == 422 and any("expired" in b["message"] for b in r.json()["detail"]["blockers"])
    commercial(admin, s, status="complimentary", reason="Goodwill extension for one month")
    assert admin.post(f"/admin/sites/{s['id']}/publish", json={}).status_code == 200


def test_commercially_suspending_a_live_site_takes_it_offline_and_restoring_does_not_republish_by_itself(admin, sites_on):
    biz, s = live_site(admin)
    assert commercial(admin, s, status="suspended", reason="Chargeback dispute").json()["status"] == "suspended" and sites_on.read(s["hostname"]) is None
    commercial(admin, s, status="paid_offline", billing_period="monthly", paid_until=(utcnow() + timedelta(days=30)).date().isoformat())
    assert sites_on.read(s["hostname"]) is None  # an explicit Resume is needed
    assert admin.post(f"/admin/sites/{s['id']}/unsuspend").status_code == 200 and sites_on.read(s["hostname"])


def test_a_site_can_be_deleted_only_when_not_published_and_its_name_is_then_held(admin, sites_on):
    biz, s = live_site(admin)
    assert admin.delete(f"/admin/sites/{s['id']}").status_code == 409
    admin.post(f"/admin/sites/{s['id']}/unpublish")
    assert admin.delete(f"/admin/sites/{s['id']}").status_code == 204
    assert sites_on.resolve_site_hostname(s["hostname"]) is None and owner_query("SELECT count(*) FROM sites WHERE id = :s", s=s["id"])[0][0] == 0
    assert owner_query("SELECT reason FROM site_slug_quarantine WHERE slug = :s", s=s["site_slug"])[0][0] == "deleted"
    other = create(admin)
    r = admin.post(f"/admin/tenants/{other['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON, "site_slug": s["site_slug"]})
    assert r.status_code == 409 and "held until" in r.json()["detail"]["message"]
    again = new_site(admin, biz, site_slug=s["site_slug"])  # the business that held it may take it back
    assert again["site_slug"] == s["site_slug"]


# ================================================================================================================ 8. site names
def test_renaming_holds_the_old_name_for_90_days_and_needs_the_site_to_be_offline(admin, sites_on):
    biz, s = live_site(admin)
    assert admin.post(f"/admin/sites/{s['id']}/slug", json={"site_slug": "brand-new-name"}).status_code == 409
    admin.post(f"/admin/sites/{s['id']}/unpublish")
    new = f"renamed-{uuid.uuid4().hex[:6]}"
    r = admin.post(f"/admin/sites/{s['id']}/slug", json={"site_slug": new})
    assert r.status_code == 200 and r.json()["site_slug"] == new and r.json()["hostname"] == f"{new}.{BASE}" and [d["hostname"] for d in r.json()["domains"]] == [f"{new}.{BASE}"]
    q = owner_query("SELECT release_until - released_at, reason FROM site_slug_quarantine WHERE slug = :s", s=s["site_slug"])[0]
    assert q[0] >= timedelta(days=89, hours=23) and q[1] == "renamed"
    other = create(admin)
    assert admin.post(f"/admin/tenants/{other['id']}/site", json={"commercial_status": "complimentary", "commercial_reason": REASON, "site_slug": s["site_slug"]}).status_code == 409
    owner_exec("UPDATE site_slug_quarantine SET release_until = now() - interval '1 day' WHERE slug = :s", s=s["site_slug"])
    assert new_site(admin, other, site_slug=s["site_slug"])["site_slug"] == s["site_slug"]  # after 90 days anyone may have it
    assert admin.post(f"/admin/sites/{s['id']}/slug", json={"site_slug": "www"}).status_code == 422


def test_changing_the_template_keeps_the_business_details_and_matching_sections(admin, sites_on):
    s = new_site(admin, create(admin), template_key="clinic")
    c = complete(s["draft_content"], "clinic")
    c["business"]["tagline"] = "Kept across templates"
    for sec in c["sections"]:
        if sec["type"] == "faqs":
            sec["data"]["items"] = [{"question": "Do you take walk-ins?", "answer": "Yes."}]
    s = save(admin, s, c)
    r = admin.post(f"/admin/sites/{s['id']}/template", json={"template_key": "professional"})
    assert r.status_code == 200
    out = r.json()
    assert out["template_key"] == "professional" and out["draft_content"]["business"]["tagline"] == "Kept across templates"
    assert [x["type"] for x in out["draft_content"]["sections"]] != [x["type"] for x in c["sections"]]
    faq = next(x for x in out["draft_content"]["sections"] if x["type"] == "faqs")
    assert faq["data"]["items"][0]["question"] == "Do you take walk-ins?"
    assert not any(x["type"] in ("conditions", "disclaimer") for x in out["draft_content"]["sections"])
    assert admin.post(f"/admin/sites/{s['id']}/template", json={"template_key": "nonsense"}).status_code == 422
    biz, live = live_site(admin)
    assert admin.post(f"/admin/sites/{live['id']}/template", json={"template_key": "salon"}).status_code == 409  # unpublish first


# ================================================================================================================ 9. images
def test_image_upload_dedupe_alt_text_reorder_and_removal(admin, sites_on):
    s = new_site(admin, create(admin))
    up = lambda data, **p: admin.post(f"/admin/sites/{s['id']}/assets", content=data, headers={"Content-Type": "application/octet-stream"}, params=p)  # noqa: E731
    r = up(jpeg(exif=True), alt_text="The waiting room")
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["alt_text"] == "The waiting room"
    aid = r.json()["id"]
    assert up(jpeg(exif=True)).json()["created"] is False and up(jpeg(exif=True)).json()["id"] == aid  # the same picture is not stored twice
    stored = owner_query("SELECT data, storage_key, content_type FROM site_assets WHERE id = :a", a=aid)[0]
    assert b"Exif" not in bytes(stored[0]) and b"SecretPhoneMaker" not in bytes(stored[0]) and stored[1].startswith("assets/") and stored[2] == "image/webp"
    f = admin.get(f"/admin/sites/{s['id']}/assets/{aid}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "image/webp" and f.headers["x-content-type-options"] == "nosniff" and Image.open(io.BytesIO(f.content)).format == "WEBP"
    assert admin.patch(f"/admin/sites/{s['id']}/assets/{aid}", json={"alt_text": "Reception desk", "sort_order": 3}).json() == {"id": aid, "alt_text": "Reception desk", "sort_order": 3}
    # an image used in the draft is removed from the draft when it is deleted
    c = admin.get(f"/admin/sites/{s['id']}").json()
    c["draft_content"]["sections"][0]["data"]["image"] = aid
    c["draft_content"]["business"]["logo"] = aid
    save(admin, c, c["draft_content"])
    assert admin.delete(f"/admin/sites/{s['id']}/assets/{aid}").status_code == 204
    after = admin.get(f"/admin/sites/{s['id']}").json()
    assert after["draft_content"]["sections"][0]["data"]["image"] is None and after["draft_content"]["business"]["logo"] is None and after["assets"] == []


@pytest.mark.parametrize("data,status", [(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', 415), (b"GIF89a" + b"\x00" * 40, 415), (b"not an image", 415), (b"", 422),
                                         (b"\xff\xd8\xff" + b"\x00" * 100, 422)])
def test_malicious_or_wrong_uploads_are_refused(admin, sites_on, data, status):
    s = new_site(admin, create(admin))
    r = admin.post(f"/admin/sites/{s['id']}/assets", content=data, headers={"Content-Type": "image/png"})  # the declared type is ignored
    assert r.status_code == status, r.text
    assert owner_query("SELECT count(*) FROM site_assets WHERE site_id = :s", s=s["id"])[0][0] == 0


def test_oversized_uploads_and_per_site_limits(admin, sites_on, monkeypatch):
    s = new_site(admin, create(admin))
    r = admin.post(f"/admin/sites/{s['id']}/assets", content=b"\xff\xd8\xff" + b"\x00" * (8 * 1024 * 1024 + 10), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413
    monkeypatch.setattr("app.services.sites.media.MAX_ASSETS_PER_SITE", 2)
    for color in ((255, 0, 0), (0, 255, 0)):
        assert admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(color=color), headers={"Content-Type": "image/jpeg"}).status_code == 201
    r = admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(color=(0, 0, 255)), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many_images"
    monkeypatch.setattr("app.services.sites.media.MAX_ASSETS_PER_SITE", 24)
    monkeypatch.setattr("app.services.sites.media.MAX_SITE_BYTES", 10)
    r = admin.post(f"/admin/sites/{s['id']}/assets", content=png(), headers={"Content-Type": "image/png"}, params={"kind": "logo"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "storage_full"


def test_publishing_needs_alt_text_and_publishes_only_the_images_the_site_uses(admin, sites_on):
    s = new_site(admin, create(admin))
    img = admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(), headers={"Content-Type": "image/jpeg"}).json()["id"]
    spare = admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(color=(1, 200, 1)), headers={"Content-Type": "image/jpeg"}, params={"alt_text": "Unused spare"}).json()["id"]
    c = complete(admin.get(f"/admin/sites/{s['id']}").json()["draft_content"], s["template_key"])
    c["sections"][0]["data"]["image"] = img
    s = save(admin, s, c)
    r = admin.post(f"/admin/sites/{s['id']}/publish", json={})
    assert r.status_code == 422 and any("alt text" in b["message"] for b in r.json()["detail"]["blockers"])
    admin.patch(f"/admin/sites/{s['id']}/assets/{img}", json={"alt_text": "The reception"})
    publish(admin, s)
    sha_used = owner_query("SELECT sha256 FROM site_assets WHERE id = :a", a=img)[0][0]
    sha_spare = owner_query("SELECT sha256 FROM site_assets WHERE id = :a", a=spare)[0][0]
    assert sites_on.read(s["hostname"], f"assets/{sha_used[:16]}.webp") and sites_on.read(s["hostname"], f"assets/{sha_spare[:16]}.webp") is None
    assert f"/assets/{sha_used[:16]}.webp" in sites_on.read(s["hostname"]).decode() and 'alt="The reception"' in sites_on.read(s["hostname"]).decode()


# ================================================================================================================ 10. enquiries
def test_the_enquiry_endpoint_needs_the_service_token(admin, sites_on):
    _, s = live_site(admin)
    assert enquire(s["hostname"], token=None).status_code == 403 and enquire(s["hostname"], token="wrong" * 10).status_code == 403 and enquire(s["hostname"], token=TOKEN[:-1] + "x").status_code == 403
    assert owner_query("SELECT count(*) FROM site_enquiries")[0][0] >= 0
    assert enquire(s["hostname"]).status_code == 201


def test_the_enquiry_endpoint_does_not_exist_without_a_configured_token(admin, sites_on, monkeypatch):
    _, s = live_site(admin)
    monkeypatch.setattr(settings, "sites_service_token", "")
    assert enquire(s["hostname"], token="anything").status_code == 404


def test_cookies_play_no_part_in_the_enquiry_endpoint_and_nothing_is_set(admin, sites_on):
    _, s = live_site(admin)
    # an administrator's own session cookies, sent without the token, do not open the route
    r = admin.post("/site-enquiry", json={"host": s["hostname"], "name": "x y", "message": "hello there", "consent": True, "phone": "98765 43210"})
    assert r.status_code == 403
    ok = enquire(s["hostname"])
    assert ok.status_code == 201 and "set-cookie" not in {k.lower() for k in ok.headers}


def test_a_visitors_enquiry_is_stored_with_consent_and_a_keyed_ip_hash_only(admin, sites_on):
    biz, s = live_site(admin)
    r = enquire(s["hostname"], email="Asha@Example.com", client_ip="198.51.100.9")
    assert r.status_code == 201 and r.json() == {"ok": True}
    row = owner_query("SELECT name, phone, email, message, status, consent_at IS NOT NULL, ip_hash, tenant_id::text FROM site_enquiries WHERE site_id = :s", s=s["id"])[0]
    assert row[:5] == ("Asha Verma", "+91 98765 43210", "asha@example.com", "Do you have a slot on Friday?", "new") and row[5] and row[7] == biz["id"]
    assert row[6] and len(row[6]) == 32 and "198.51.100.9" not in row[6]
    assert owner_query("SELECT count(*) FROM site_enquiries WHERE ip_hash LIKE '%198.51.100.9%'")[0][0] == 0


@pytest.mark.parametrize("over,code", [({"consent": False}, "consent_required"), ({"name": "A"}, "invalid"), ({"message": "hi"}, "invalid"), ({"phone": "", "email": ""}, "contact_required"), ({"phone": "123"}, "invalid_phone"),
                                       ({"phone": "", "email": "not-an-email"}, "invalid_email")])
def test_invalid_enquiries_are_refused_and_nothing_is_stored(admin, sites_on, over, code):
    _, s = live_site(admin)
    r = enquire(s["hostname"], **over)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert owner_query("SELECT count(*) FROM site_enquiries WHERE site_id = :s", s=s["id"])[0][0] == 0


def test_a_filled_honeypot_looks_like_a_success_and_stores_nothing(admin, sites_on):
    _, s = live_site(admin)
    r = enquire(s["hostname"], website="http://spam.example")
    assert r.status_code == 201 and r.json() == {"ok": True}
    assert owner_query("SELECT count(*) FROM site_enquiries WHERE site_id = :s", s=s["id"])[0][0] == 0


def test_enquiries_are_rate_limited_per_visitor_and_per_site(admin, sites_on):
    _, s = live_site(admin)
    codes = [enquire(s["hostname"], message=f"Question number {i} please").status_code for i in range(7)]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]
    assert enquire(s["hostname"], client_ip="203.0.113.99").status_code == 201  # a different visitor is not blocked
    assert owner_query("SELECT count(*) FROM site_enquiries WHERE site_id = :s", s=s["id"])[0][0] == 6


@pytest.mark.parametrize("how", ["unknown", "unpublished", "suspended", "expired_lapsed", "draft", "reserved_host", "other_domain"])
def test_unknown_unpublished_suspended_and_unpaid_sites_all_answer_the_same_404(admin, sites_on, how):
    biz, s = live_site(admin)
    host = s["hostname"]
    if how == "unknown":
        host = f"nobody-{uuid.uuid4().hex[:8]}.{BASE}"
    elif how == "unpublished":
        admin.post(f"/admin/sites/{s['id']}/unpublish")
    elif how == "suspended":
        admin.post(f"/admin/sites/{s['id']}/suspend", json={"reason": "Reported for misleading claims"})
    elif how == "expired_lapsed":
        commercial(admin, s, status="suspended", reason="Chargeback dispute")
    elif how == "draft":
        host = new_site(admin, create(admin))["hostname"]
    elif how == "reserved_host":
        host = f"www.{BASE}"
    elif how == "other_domain":
        host = f"{s['site_slug']}.evil.example"
    r = enquire(host)
    assert r.status_code == 404 and r.json() == {"detail": {"code": "not_found", "message": "Not found."}}


def test_the_admin_inbox_lists_marks_and_exports_the_enquiries_of_that_site_only(admin, sites_on):
    biz, s = live_site(admin)
    _, other = live_site(admin)
    enquire(s["hostname"], message="First enquiry please", client_ip="203.0.113.1")
    enquire(s["hostname"], name="Bina Rao", message="=HYPERLINK(\"http://evil.example\") call me", client_ip="203.0.113.2")
    enquire(other["hostname"], message="Belongs to the other business", client_ip="203.0.113.3")
    inbox = admin.get(f"/admin/sites/{s['id']}/enquiries").json()
    assert inbox["total"] == 2 and all("other business" not in e["message"] for e in inbox["items"]) and {e["status"] for e in inbox["items"]} == {"new"}
    eid = inbox["items"][0]["id"]
    assert admin.get(f"/admin/sites/{other['id']}/enquiries").json()["total"] == 1
    assert admin.patch(f"/admin/sites/{other['id']}/enquiries/{eid}", json={"status": "resolved"}).status_code == 404  # another site's inbox cannot touch it
    r = admin.patch(f"/admin/sites/{s['id']}/enquiries/{eid}", json={"status": "contacted"})
    assert r.status_code == 200 and r.json()["status"] == "contacted" and r.json()["contacted_at"]
    r = admin.patch(f"/admin/sites/{s['id']}/enquiries/{eid}", json={"status": "resolved"})
    assert r.json()["resolved_at"] and admin.patch(f"/admin/sites/{s['id']}/enquiries/{eid}", json={"status": "deleted"}).status_code == 422
    assert admin.get(f"/admin/sites/{s['id']}/enquiries", params={"status": "new"}).json()["total"] == 1
    csv = admin.get(f"/admin/sites/{s['id']}/enquiries.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and "no-store" in csv.headers["cache-control"]
    assert "'=HYPERLINK" in csv.text and "\n=HYPERLINK" not in csv.text and ",=HYPERLINK" not in csv.text and "Belongs to the other business" not in csv.text and csv.text.startswith("received,status,name")
    assert {"admin.site_enquiry_status", "admin.site_enquiries_export"} <= set(audit_actions(biz["id"]))
    assert "site_enquiry" not in owner_query("SELECT COALESCE(string_agg(DISTINCT metadata::text, ','), '') FROM audit_logs WHERE tenant_id = :t AND action LIKE 'admin.site_enquiry%'", t=biz["id"])[0][0]  # no visitor details in the log


def test_enquiries_are_deleted_after_the_retention_period(admin, sites_on):
    _, s = live_site(admin)
    enquire(s["hostname"], message="An old enquiry here", client_ip="203.0.113.1")
    enquire(s["hostname"], message="A recent enquiry here", client_ip="203.0.113.2")
    owner_exec("UPDATE site_enquiries SET created_at = now() - make_interval(days => :d) WHERE message LIKE 'An old%' AND site_id = :s", d=settings.sites_enquiry_retention_days + 1, s=s["id"])
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert svc.purge_old_enquiries(db) >= 1
        db.commit()
    left = [r[0] for r in owner_query("SELECT message FROM site_enquiries WHERE site_id = :s", s=s["id"])]
    assert left == ["A recent enquiry here"]


def test_a_failing_notifier_never_loses_an_enquiry(admin, sites_on, monkeypatch):
    class Boom(svc.Notifier):
        def new_enquiry(self, site, enquiry):
            raise RuntimeError("mail is down")

    monkeypatch.setattr(svc, "get_notifier", lambda: Boom())
    _, s = live_site(admin)
    assert enquire(s["hostname"]).status_code == 201 and owner_query("SELECT count(*) FROM site_enquiries WHERE site_id = :s", s=s["id"])[0][0] == 1


def test_no_email_is_sent_by_default(admin, sites_on):
    from app.services.mailer import OUTBOX

    _, s = live_site(admin)
    n = len(OUTBOX)
    enquire(s["hostname"])
    assert len(OUTBOX) == n and settings.sites_enquiry_notifier == "none"


# ================================================================================================================ 11. account export and deletion
def test_the_account_export_includes_the_website_and_its_image_files_and_nothing_of_another_business(admin, sites_on):
    biz, s = live_site(admin)
    img = admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(), headers={"Content-Type": "image/jpeg"}, params={"alt_text": "Reception"}).json()["id"]
    enquire(s["hostname"])
    other_biz, other = live_site(admin)
    enquire(other["hostname"], message="Another business enquiry")
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        from app.models import Tenant

        data, manifest = account_svc.build_export(db, db.get(Tenant, uuid.UUID(biz["id"])))
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"sites.json", "site_domains.json", "site_assets.json", "site_enquiries.json", "site_revisions.json", f"site_files/{img}.webp"} <= names
    blob = b"".join(z.read(n) for n in names if n.endswith(".json")).decode()
    assert "Another business enquiry" not in blob and other["hostname"] not in blob and other["id"] not in blob and "Do you have a slot on Friday?" in blob and s["hostname"] in blob
    assert "\"data\"" not in z.read("site_assets.json").decode()  # image bytes are files in the ZIP, not text inside the JSON
    assert Image.open(io.BytesIO(z.read(f"site_files/{img}.webp"))).format == "WEBP"


def test_deleting_a_business_takes_its_website_offline_removes_its_files_and_holds_the_name(admin, sites_on):
    biz, s = live_site(admin)
    admin.post(f"/admin/sites/{s['id']}/assets", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    assert sites_on.read(s["hostname"])
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert account_svc.delete_tenant(db, uuid.UUID(biz["id"]))["deleted"] is True
    assert sites_on.read(s["hostname"]) is None and sites_on.resolve_site_hostname(s["hostname"]) is None
    assert not (sites_on.root / "sites" / s["id"]).exists()
    assert owner_query("SELECT count(*) FROM sites WHERE tenant_id = :t", t=biz["id"])[0][0] == 0 and owner_query("SELECT count(*) FROM site_assets WHERE tenant_id = :t", t=biz["id"])[0][0] == 0
    q = owner_query("SELECT reason, release_until > now() + interval '89 days' FROM site_slug_quarantine WHERE slug = :s", s=s["site_slug"])[0]
    assert q == ("business_deleted", True)


def test_a_business_is_not_deleted_while_its_website_cannot_be_taken_down(admin, sites_on, monkeypatch):
    biz, s = live_site(admin)

    def boom(site_id, hosts):
        raise HostingError("delete_failed", "R2 could not delete a file (HTTP 503).", retryable=True)

    monkeypatch.setattr(sites_on, "delete_site", boom)
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        with pytest.raises(svc.SiteError):
            account_svc.delete_tenant(db, uuid.UUID(biz["id"]))
        db.rollback()
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=biz["id"])[0][0] == 1 and sites_on.read(s["hostname"])  # nothing was deleted, and the site is still up for the retry


def test_deleting_a_business_with_no_website_is_unchanged(admin, sites_on):
    biz = create(admin)
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert account_svc.delete_tenant(db, uuid.UUID(biz["id"]))["deleted"] is True


# ================================================================================================================ 12. cookie and origin isolation
def test_no_business_hostname_is_ever_allowed_by_cors(admin, sites_on):
    _, s = live_site(admin)
    r = anon().options("/api/v1/site-enquiry", headers={"Origin": f"https://{s['hostname']}", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
    r = anon().options("/api/v1/auth/login", headers={"Origin": f"https://{s['hostname']}", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_production_refuses_to_start_with_sites_inside_the_cookie_domain_unless_that_is_acknowledged():
    cf = dict(sites_enabled=True, sites_provider="cloudflare", sites_base_domain="flowqr.site", sites_service_token="s" * 40, cloudflare_account_id="a", cloudflare_api_token="t", cloudflare_kv_namespace_id="k",
              r2_bucket="b", r2_access_key_id="i", r2_secret_access_key="s")
    base = config_problems(good(cookie_domain=".flowqr.site", frontend_url="https://www.flowqr.site", cors_origins="https://www.flowqr.site", **cf))
    assert any("COOKIE_DOMAIN" in p and "SITES_BASE_DOMAIN" in p for p in base), base
    assert not any("SITES_" in p for p in config_problems(good(cookie_domain=".flowqr.site", frontend_url="https://www.flowqr.site", cors_origins="https://www.flowqr.site", sites_accept_shared_cookie_scope=True, **cf)))
    assert not any("COOKIE_DOMAIN" in p and "SITES_BASE_DOMAIN" in p for p in config_problems(good(cookie_domain=".flowqr.site", frontend_url="https://www.flowqr.site", cors_origins="https://www.flowqr.site",
                                                                                                    **{**cf, "sites_base_domain": "flowqr-sites.example"})))


@pytest.mark.parametrize("over,needle", [({"sites_service_token": "short"}, "SITES_SERVICE_TOKEN"), ({"sites_provider": "local"}, "SITES_PROVIDER"), ({"cloudflare_api_token": ""}, "CLOUDFLARE_API_TOKEN"),
                                         ({"r2_secret_access_key": ""}, "R2_SECRET_ACCESS_KEY"), ({"sites_base_domain": "sites.localhost"}, "SITES_BASE_DOMAIN")])
def test_production_needs_complete_hosting_settings_when_sites_are_enabled(over, needle):
    cf = dict(sites_enabled=True, sites_provider="cloudflare", sites_base_domain="flowqr-sites.example", sites_service_token="s" * 40, cloudflare_account_id="a", cloudflare_api_token="t",
              cloudflare_kv_namespace_id="k", r2_bucket="b", r2_access_key_id="i", r2_secret_access_key="s")
    assert config_problems(good(**{**cf})) == [] or not any("SITES_" in p or "CLOUDFLARE" in p or "R2_" in p for p in config_problems(good(**cf)))
    assert any(needle in p for p in config_problems(good(**{**cf, **over})))


def test_production_with_sites_disabled_ignores_every_sites_setting():
    assert not any("SITES" in p or "CLOUDFLARE" in p or "R2_" in p for p in config_problems(good(sites_enabled=False, sites_provider="local", sites_service_token="")))


# ================================================================================================================ 13. housekeeping and other businesses
def test_the_housekeeping_job_runs_the_checks_when_sites_are_on(admin, sites_on):
    from app.workers.tasks import sites_housekeeping

    biz, s = live_site(admin)
    admin.post(f"/admin/tenants/{biz['id']}/suspend", json={"reason": "non-payment of the card fee"})
    out = sites_housekeeping()
    assert out["enquiries_deleted"] >= 0 and "suspended" in out


def test_existing_businesses_are_untouched_by_the_website_feature(admin, biz_a, sites_on):
    before = owner_query("SELECT count(*), md5(string_agg(id::text || name || slug || is_active::text, ',' ORDER BY id::text)) FROM tenants WHERE id = :t", t=biz_a.tenant_id)[0]
    new_site(admin, {"id": biz_a.tenant_id})
    assert owner_query("SELECT count(*), md5(string_agg(id::text || name || slug || is_active::text, ',' ORDER BY id::text)) FROM tenants WHERE id = :t", t=biz_a.tenant_id)[0] == before
    assert biz_a.get("/tenant").json()["id"] == biz_a.tenant_id and biz_a.get("/locations").status_code == 200
