"""The connected Google Business Profile's profile (logo) photo, shown as the business avatar: read from the saved snapshot (no call to Google), only a Google-hosted https link, scoped like every
other page, and silent (null) when there is no such photo. Real application and PostgreSQL; nothing talks to Google."""
import json

from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401

GOOD = "https://lh3.googleusercontent.com/p/AF1QipExample=s400"


def put(gl_id, media):
    t = owner_query("SELECT tenant_id FROM google_locations WHERE id = :g", g=str(gl_id))[0][0]
    owner_exec("INSERT INTO gbp_snapshots (id, tenant_id, google_location_id, media, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, CAST(:m AS jsonb), now(), now()) "
               "ON CONFLICT (google_location_id) DO UPDATE SET media = EXCLUDED.media", t=str(t), g=str(gl_id), m=json.dumps(media))


def test_the_profile_photo_link_is_returned(connected, gid):  # noqa: F811
    put(gid, [{"name": "m/1", "category": "ADDITIONAL", "created_at": None}, {"name": "m/2", "category": "PROFILE", "created_at": None, "url": GOOD}])
    r = connected.get("/agent/business-photo")
    assert r.status_code == 200 and r.json() == {"url": GOOD, "source": "google_business_profile"}
    assert "private" in r.headers["cache-control"]


def test_no_profile_photo_means_null_not_another_photo(connected, gid):  # noqa: F811
    put(gid, [{"name": "m/1", "category": "COVER", "created_at": None, "url": GOOD}, {"name": "m/2", "category": "ADDITIONAL", "created_at": None, "url": GOOD}])
    assert connected.get("/agent/business-photo").json() == {"url": None, "source": None}


def test_an_old_snapshot_without_the_link_and_a_link_not_on_googles_host_both_give_null(connected, gid):  # noqa: F811
    put(gid, [{"name": "m/2", "category": "PROFILE", "created_at": None}])
    assert connected.get("/agent/business-photo").json()["url"] is None
    put(gid, [{"name": "m/2", "category": "PROFILE", "created_at": None, "url": "https://evil.example/logo.png"}])
    assert connected.get("/agent/business-photo").json()["url"] is None


def test_no_snapshot_at_all_is_null(connected, gid):  # noqa: F811
    owner_exec("DELETE FROM gbp_snapshots WHERE google_location_id = :g", g=str(gid))
    assert connected.get("/agent/business-photo").json() == {"url": None, "source": None}


def test_another_business_never_sees_it(connected, gid, biz_b):  # noqa: F811
    put(gid, [{"name": "m/2", "category": "PROFILE", "created_at": None, "url": GOOD}])
    assert biz_b.get("/agent/business-photo").json()["url"] is None


def test_the_snapshot_keeps_the_link_only_for_the_profile_photo():
    from app.services.agent.snapshots import snapshot_media
    out = snapshot_media([{"name": "a", "category": "PROFILE", "google_url": GOOD, "url": "https://x.example/ignored", "created_at": "t"}, {"name": "b", "category": "ADDITIONAL", "google_url": GOOD, "created_at": "t"},
                          {"name": "c", "category": "COVER", "google_url": GOOD}, {"name": "d", "category": "PROFILE"}])
    assert out[0] == {"name": "a", "category": "PROFILE", "created_at": "t", "url": GOOD}
    assert out[1] == {"name": "b", "category": "ADDITIONAL", "created_at": "t"} and "url" not in out[2]
    assert out[3]["url"] is None  # a profile photo without a link stays linkless (the endpoint then answers null)
