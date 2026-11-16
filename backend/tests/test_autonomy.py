"""The autonomy matrix is not a brochure: it is served from code, and the claims it makes about the workflow are checked against real rows.
Google is a test double and the AI a scripted stub (see test_agent.py); PostgreSQL, RLS and the state machines are real."""
from app.services.agent import autonomy
from tests.test_agent import ai, add_review, tasks  # noqa: F401
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite

SIX = {"seo", "review_growth", "replies", "posts", "photos", "analytics"}


def test_matrix_covers_all_six_capabilities_with_the_connected_workflow():
    m = autonomy.matrix()
    assert {c["id"] for c in m["capabilities"]} == SIX
    assert [s["id"] for s in m["stages"]] == ["collect", "analyze", "recommend", "prepare", "approve", "publish", "verify", "report"]
    assert m["auto_publish"] is False
    for c in m["capabilities"]:
        assert c["independent"] and c["verification"] and c["never"] and c["sources"], c["id"]
        if c["id"] != "analytics":  # analytics is read-only; everything else changes something public
            assert c["needs_approval"] and "Nothing" not in c["needs_approval"][0], c["id"]


def test_only_the_owner_side_approves_and_the_agent_never_does():
    approvers = {s["id"]: s["actor"] for s in autonomy.matrix()["stages"]}
    assert approvers["approve"] == "owner" and all(a != "owner" for k, a in approvers.items() if k != "approve")


def test_endpoint_returns_matrix_and_live_pipeline_for_any_member(connected, fake, gid, ai):  # noqa: F811
    r = connected.get("/agent/autonomy")
    assert r.status_code == 200 and {c["id"] for c in r.json()["capabilities"]} == SIX
    assert invite(connected).get("/agent/autonomy").status_code == 200
    p = r.json()["pipeline"]
    assert p["approve"]["waiting"] == 0 and p["publish"]["queued"] == 0 and p["failed"] == 0


def test_pipeline_follows_a_reply_from_draft_to_published_and_nothing_skips_approval(connected, fake, gid, ai):  # noqa: F811
    add_review(connected, gid, 2, "Slow service", days_ago=2)
    connected.put("/agent/settings", json={"auto_draft_replies": True, "auto_publish": True})  # auto_publish is not a setting: it is ignored
    assert connected.get("/agent/settings").json()["auto_publish"] is False
    connected.post("/agent/plan/run")
    p = connected.get("/agent/autonomy").json()["pipeline"]
    assert p["approve"]["reply_drafts"] == 1 and p["approve"]["waiting"] >= 1 and p["publish"]["published_30d"] == 0 and fake.replies == []  # prepared, not published

    t = next(x for x in tasks(connected) if x["kind"] == "reply_review")
    did = t["reply"]["id"]
    # Phase 0: a 1-2 star review is always read by a person first, even with no flagged word in it ("Slow service"): approval needs the flag acknowledged.
    assert connected.post(f"/reply-drafts/{did}/approve", json={}).status_code == 409
    assert connected.post(f"/reply-drafts/{did}/approve", json={"acknowledge_flags": True}).status_code == 200
    assert fake.replies == []  # approval alone does not reach Google until the publish step runs
    assert connected.post(f"/reply-drafts/{did}/publish").json()["status"] == "published"
    p = connected.get("/agent/autonomy").json()["pipeline"]
    assert len(fake.replies) == 1 and p["publish"]["replies"] == 1 and p["verify"]["confirmed_by_google_30d"] >= 1 and p["approve"]["reply_drafts"] == 0


def test_pipeline_counts_are_per_business(connected, fake, gid, ai, biz_b):  # noqa: F811
    add_review(connected, gid, 2, "Slow service", days_ago=2)
    connected.put("/agent/settings", json={"auto_draft_replies": True})
    connected.post("/agent/plan/run")
    assert connected.get("/agent/autonomy").json()["pipeline"]["approve"]["reply_drafts"] == 1
    other = biz_b.get("/agent/autonomy").json()["pipeline"]
    assert other["approve"]["waiting"] == 0 and other["collect"]["snapshots"] == 0
