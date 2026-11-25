"""Websites hosted by FlowQR: publish, serve (sandboxed), live Google reviews, the enquiry form, the owner's Google photos, and the proposed Google profile link.

MOCKED: the AI is `Scripted`, Google is the test double and photo downloads are stubbed. The database, row-level security, publish checks, renderer and routes are real."""
import io
import uuid

import pytest
from PIL import Image

from app.core.config import Settings, config_problems, settings
from app.services import google as g
from app.services.sites import generator as gen
from app.services.sites import hosting
from tests.conftest import owner_exec, owner_query
from tests.test_agent import add_review
from tests.test_gbp import FakeGbpProvider, gid  # noqa: F401
from tests.test_google_and_reviews import connected, fake  # noqa: F401
from tests.test_website_generation import KB, on, work  # noqa: F401


def png(colour=(20, 120, 100)):
    b = io.BytesIO()
    Image.new("RGB", (900, 600), colour).save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def hosted(monkeypatch, on, connected, gid):  # noqa: F811
    """A connected business with no website, FlowQR hosting on, two Google photos and a logo, and three reviews of different star levels."""
    monkeypatch.setattr(settings, "sites_enabled", True)
    monkeypatch.setattr(settings, "sites_provider", "app")
    monkeypatch.setattr(settings, "frontend_url", "https://flowqr.test")
    provider = FakeGbpProvider()
    provider.details.update({"services": ["Dry needling"], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}], "primary_category": {"id": "x", "name": "Physiotherapist"}})
    provider.media = [{"name": "m1", "category": "EXTERIOR", "google_url": "https://lh3.googleusercontent.com/ext"}, {"name": "m2", "category": "COVER", "google_url": "https://lh3.googleusercontent.com/cover"},
                      {"name": "m3", "category": "LOGO", "google_url": "https://lh3.googleusercontent.com/logo"}, {"name": "m4", "category": "INTERIOR", "google_url": "https://lh3.googleusercontent.com/int"}]
    monkeypatch.setattr(g, "get_google_provider", lambda: provider)
    colours = {"ext": (10, 90, 80), "cover": (200, 60, 20), "logo": (0, 0, 0), "int": (90, 90, 200)}
    fetched = []
    monkeypatch.setattr(gen, "fetch_photo", lambda url: fetched.append(url) or png(colours[url.rsplit("/", 1)[1]]))
    biz = connected
    biz.put("/tenant/website-interest", json={"interest": "wants_site"})
    biz.put("/agent/knowledge", json=KB)
    owner_exec("UPDATE tenants SET phone = '+91 98765 43210' WHERE id = :t", t=uuid.UUID(biz.tenant_id))
    biz.http.put(f"/api/v1/google/connections/{biz.conn_id}/selection", json={"selections": [{"google_location_id": gid, "selected": True, "location_id": biz.location_id}]}, headers={"X-CSRF-Token": biz.csrf})
    add_review(biz, gid, rating=5, text="Wonderful care and a calm clinic")
    add_review(biz, gid, rating=2, text="The wait was long")
    add_review(biz, gid, rating=4, text="Helpful staff")
    assert work(on[0])[0] == "completed"
    biz.provider, biz.fetched = provider, fetched
    return biz


def activate(biz):
    owner_exec("UPDATE sites SET commercial_status = 'complimentary', commercial_reason = 'test activation' WHERE tenant_id = :t", t=uuid.UUID(biz.tenant_id))


def publish(biz):
    activate(biz)
    r = biz.post("/website/publish", json={})
    assert r.status_code == 200 and r.json()["published"] is True, r.text
    slug = owner_query("SELECT site_slug FROM sites WHERE tenant_id = :t", t=uuid.UUID(biz.tenant_id))[0][0]
    return r.json(), slug


def get(biz, slug, path=""):
    return biz.http.get(f"/api/v1/public-site/{slug}{'/' + path if path else ''}")


def test_google_photos_reviews_and_facts_are_in_the_draft(hosted):
    st = hosted.get("/website").json()
    photos = st["site"]["photos"]
    assert sum(p["kind"] == "photo" for p in photos) == 3 and sum(p["kind"] == "logo" for p in photos) == 1
    assert all(u.startswith("https://lh3.googleusercontent.com/") for u in hosted.fetched)
    secs = {s["type"]: s for s in st["site"]["sections"] if s["enabled"]}
    assert "reviews" in secs and "gallery" in secs and secs["hero"]["data"]["image"] and secs["about"]["data"]["highlights"] == ["Physiotherapist"]
    assert next(s for s in st["job"]["steps"] if s["key"] == "images")["note"].startswith("3 photo(s) copied")
    thumb = hosted.get(f"/website/photo/{photos[0]['id']}")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    after = hosted.delete(f"/website/photo/{photos[-1]['id']}").json()
    assert len(after["site"]["photos"]) == len(photos) - 1


def test_publish_serves_the_snapshot_sandboxed_with_every_star_level_and_live_reviews(hosted, gid):  # noqa: F811
    out, slug = publish(hosted)
    assert out["state"]["publish"]["url"].endswith(f"/site/{slug}/")
    r = get(hosted, slug)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "allow-scripts" not in csp and "allow-same-origin" not in csp and "script-src 'none'" in csp and r.headers["x-content-type-options"] == "nosniff"
    html = r.text
    assert "noindex" not in html and f'href="/site/{slug}/style.' in html and f'src="/site/{slug}/assets/' in html and "set-cookie" not in r.headers
    assert "Wonderful care" in html and "The wait was long" in html and "3 Google reviews" in html and "3.7" in html  # every star level, never only the good ones
    assert "Asha" in html and "<script" not in html.replace('<script type="application/ld+json">', "")
    add_review(hosted, gid, rating=1, text="A brand new review")
    assert "A brand new review" in get(hosted, slug).text and "4 Google reviews" in get(hosted, slug).text  # live, without publishing again
    css = r.text.split(f'href="/site/{slug}/')[1].split('"')[0]
    assert get(hosted, slug, css).headers["content-type"].startswith("text/css")
    asset = r.text.split(f'src="/site/{slug}/')[1].split('"')[0]
    assert get(hosted, slug, asset).headers["content-type"] == "image/webp"
    assert get(hosted, slug, "privacy").status_code == 200 and get(hosted, slug, "_manifest.json").status_code == 404 and get(hosted, "no-such-site").status_code == 404


def test_only_the_published_snapshot_is_public_and_redacted_review_text_is_gone(hosted):
    _, slug = publish(hosted)
    st = hosted.get("/website").json()
    owner_exec("UPDATE sites SET draft_content = jsonb_set(draft_content, '{seo,title}', '\"SECRET DRAFT TITLE\"') WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))
    assert "SECRET DRAFT TITLE" not in get(hosted, slug).text and st["site"]["status"] == "published"
    owner_exec("UPDATE reviews SET text = NULL, reviewer_name = NULL WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))  # what the retention job does
    html = get(hosted, slug).text
    assert "Wonderful care" not in html and "A Google user" in html and "3 Google reviews" in html
    owner_exec("UPDATE sites SET commercial_status = 'expired' WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))
    assert get(hosted, slug).status_code == 404


def test_the_enquiry_form_stores_one_enquiry_and_redirects(hosted):
    _, slug = publish(hosted)
    assert f'action="/site/{slug}/_enquiry"' in get(hosted, slug).text
    form = {"name": "Ravi Kumar", "phone": "9876500000", "message": "Do you treat knee pain?", "consent": "yes", "website": ""}
    r = hosted.http.post(f"/api/v1/public-site/{slug}/_enquiry", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/site/{slug}/thanks"
    assert owner_query("SELECT count(*) FROM site_enquiries WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))[0][0] == 1
    bad = hosted.http.post(f"/api/v1/public-site/{slug}/_enquiry", data={**form, "consent": ""}, follow_redirects=False)
    assert bad.status_code == 303 and bad.headers["location"].endswith("/problem")
    spam = hosted.http.post(f"/api/v1/public-site/{slug}/_enquiry", data={**form, "website": "http://spam"}, follow_redirects=False)
    assert spam.headers["location"].endswith("/thanks") and owner_query("SELECT count(*) FROM site_enquiries WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))[0][0] == 1


def test_publishing_proposes_the_google_link_and_writes_nothing_until_approved(hosted):
    out, slug = publish(hosted)
    assert out["google_action_id"] and "approve" in out["message"]
    row = owner_query("SELECT field_key, status, proposed_value->>'canonical' FROM agent_actions WHERE id = :a", a=uuid.UUID(out["google_action_id"]))[0]
    assert row[0] == "website" and row[1] == "pending_approval" and row[2] == f"https://flowqr.test/site/{slug}"
    assert not any(k == "update" for k, _ in hosted.provider.writes)
    again = hosted.post("/website/google-link", json={}).json()
    assert again["action_id"] == out["google_action_id"]  # the same proposal, never a second


def test_without_activation_nothing_is_served(hosted):
    slug = owner_query("SELECT site_slug FROM sites WHERE tenant_id = :t", t=uuid.UUID(hosted.tenant_id))[0][0]
    assert hosted.post("/website/publish", json={}).json()["published"] is False and get(hosted, slug).status_code == 404


def test_hosting_off_serves_nothing(hosted, monkeypatch):
    _, slug = publish(hosted)
    monkeypatch.setattr(settings, "sites_enabled", False)
    assert get(hosted, slug).status_code == 404


@pytest.mark.parametrize("url", ["http://lh3.googleusercontent.com/a", "https://evil.example/a.png", "https://googleusercontent.com.evil.example/a", "https://169.254.169.254/latest", "file:///etc/passwd", ""])
def test_photos_are_only_ever_fetched_from_googles_image_hosts_over_https(url, monkeypatch):
    monkeypatch.setattr(gen.httpx, "stream", lambda *a, **k: pytest.fail("a request was made"))
    assert gen.fetch_photo(url) is None


def test_the_production_guard_accepts_flowqr_hosting_only_with_an_https_app_address():
    base = {"app_env": "production", "sites_enabled": True, "sites_provider": "app"}
    ok = [p for p in config_problems(Settings(**base, frontend_url="https://flowqr.site")) if "SITES_" in p or "CLOUDFLARE" in p or "R2_" in p or "websites" in p.lower()]
    assert ok == []
    assert any("FRONTEND_URL must be https" in p for p in config_problems(Settings(**base, frontend_url="http://flowqr.site")))
    assert "sandbox" in hosting.APP_CSP and "allow-same-origin" not in hosting.APP_CSP


def test_the_admin_screens_show_the_address_a_person_can_actually_open(monkeypatch):
    from app.services.sites import service as svc

    monkeypatch.setattr(settings, "sites_provider", "app")
    monkeypatch.setattr(settings, "frontend_url", "https://www.flowqr.site")
    assert svc.display_address("gomti-physio") == "www.flowqr.site/site/gomti-physio"
    assert svc.public_config()["address_template"] == "www.flowqr.site/site/{slug}"
    monkeypatch.setattr(settings, "sites_provider", "local")
    assert svc.display_address("gomti-physio").startswith("gomti-physio.")
