import pytest

from app.services.ai.safety import assess_review
from app.services.ai.language import detect_language

UA = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"}


class StubProviderForTests:
    """TEST DOUBLE - not a real AI. Echoes the customer's text with light formatting."""
    name = "test-stub"
    model = "stub-1"

    def __init__(self, reply=None):
        self.reply = reply
        self.last_user = None

    def generate(self, system, user, *, max_tokens=600, temperature=0.4):
        self.last_user = user
        if self.reply is not None:
            return self.reply
        inner = user.split("<customer_text>")[1].split("</customer_text>")[0].strip()
        return inner[0].upper() + inner[1:]


@pytest.fixture()
def live_card(admin, biz_a):
    b = admin.post("/admin/batches", json={"name": "ai", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"][0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    return card


def patch_provider(monkeypatch, provider):
    monkeypatch.setattr("app.api.v1.public.get_provider", lambda: provider)


def test_assist_returns_suggestion_logs_usage_and_event(client, live_card, biz_a, monkeypatch):
    stub = StubProviderForTests()
    patch_provider(monkeypatch, stub)
    r = client.post(f"/api/v1/public/c/{live_card['public_token']}/assist",
                    json={"text": "doctor was very kind, my back pain is better now"}, headers=UA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_assisted"] is True and body["suggestion"].startswith("Doctor was very kind")
    assert "edit" in body["disclaimer"].lower()
    # instructions in the prompt preserve meaning / no fabrication, and the customer text is delimited
    assert "<customer_text>" in stub.last_user
    from tests.conftest import Session  # noqa
    from app.core.db import SessionLocal, set_rls_context
    from app.models import AIGenerationLog
    from sqlalchemy import select
    db = SessionLocal(); set_rls_context(db, bypass=True)
    logs = db.scalars(select(AIGenerationLog).where(AIGenerationLog.tenant_id == biz_a.tenant_id)).all()
    db.close()
    assert len(logs) == 1 and logs[0].status == "ok" and logs[0].input_chars > 0
    # usage log never stores the customer text
    assert not hasattr(logs[0], "input_text")
    assert biz_a.get("/cards").json()[0]["stats"]["ai_assist"] == 1


def test_assist_rejects_fabricated_bloated_output(client, live_card, monkeypatch):
    patch_provider(monkeypatch, StubProviderForTests(reply="Amazing! " * 100))
    r = client.post(f"/api/v1/public/c/{live_card['public_token']}/assist", json={"text": "it was okay, a bit of waiting"}, headers=UA)
    assert r.status_code == 503


def test_assist_unavailable_when_ai_not_configured(client, live_card):
    # settings.gemini_api_key is empty in tests => honest 503, no fake output
    r = client.post(f"/api/v1/public/c/{live_card['public_token']}/assist", json={"text": "good service and friendly staff"}, headers=UA)
    assert r.status_code == 503
    assert client.get(f"/api/v1/public/c/{live_card['public_token']}", headers=UA).json()["ai_available"] is False


def test_assist_is_rate_limited_and_requires_live_card(client, live_card, monkeypatch):
    patch_provider(monkeypatch, StubProviderForTests())
    codes = [client.post(f"/api/v1/public/c/{live_card['public_token']}/assist", json={"text": "nice clean clinic, friendly"}, headers=UA).status_code
             for _ in range(8)]
    assert codes[:6] == [200] * 6 and 429 in codes
    assert client.post("/api/v1/public/c/" + "z" * 30 + "/assist", json={"text": "hello there friend"}, headers=UA).status_code in (404, 429)


def test_negative_review_gets_same_treatment(client, live_card, monkeypatch):
    """No sentiment gating: a negative review is polished like any other and never redirected away."""
    patch_provider(monkeypatch, StubProviderForTests())
    r = client.post(f"/api/v1/public/c/{live_card['public_token']}/assist",
                    json={"text": "waited 1 hour and treatment felt rushed"}, headers=UA)
    assert r.status_code == 200
    page = client.get(f"/api/v1/public/c/{live_card['public_token']}", headers={"user-agent": UA["user-agent"] + " x"}).json()
    assert page["review_url"]  # link always offered


def test_ai_quota_enforced_per_tenant(client, live_card, biz_a, monkeypatch):
    patch_provider(monkeypatch, StubProviderForTests())
    from app.core.db import SessionLocal, set_rls_context
    from app.models import Subscription
    from sqlalchemy import select
    db = SessionLocal(); set_rls_context(db, bypass=True)
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == biz_a.tenant_id))
    sub.review_generations = 0  # the allowance the public review assistant draws on
    db.commit(); db.close()
    r = client.post(f"/api/v1/public/c/{live_card['public_token']}/assist", json={"text": "good service really"}, headers=UA)
    assert r.status_code == 503


def test_event_tracking_separates_visits_clicks(client, live_card, biz_a):
    for t in ["landing_view", "landing_view", "google_click"]:
        assert client.post(f"/api/v1/public/c/{live_card['public_token']}/event", json={"type": t}, headers=UA).status_code == 204
    assert client.post(f"/api/v1/public/c/{live_card['public_token']}/event", json={"type": "scan"}, headers=UA).status_code == 422
    stats = biz_a.get("/cards").json()[0]["stats"]
    assert stats["landing_view"] == 2 and stats["google_click"] == 1


def test_language_detection():
    assert detect_language("बहुत अच्छा अनुभव रहा") == "hi"
    assert detect_language("doctor ne bahut accha ilaaj kiya, sab kuch thik hai") == "hinglish"
    assert detect_language("The staff were friendly and helpful") == "en"


@pytest.mark.parametrize("text,rating,expected", [
    ("They did the wrong surgery, I will go to court", 1, {"medical", "legal", "low_rating"}),
    ("Receptionist was rude and overcharged me", 2, {"accusation", "low_rating"}),
    ("dhokha hai, police ko bataunga", 1, {"accusation", "legal", "low_rating"}),
    ("Great treatment, pain is gone!", 5, set()),
    ("Lovely staff", 5, set()),
])
def test_sensitive_flags(text, rating, expected):
    assert set(assess_review(text, rating)) == expected


def test_a_rejected_ai_key_pauses_the_writing_help_for_everyone_instead_of_failing_for_each_customer(client, live_card, monkeypatch):
    from app.services.ai import AIUnavailable, health

    calls = []

    class Down:
        name, model, usage = "down-stub", "m", None

        def generate(self, *a, **k):
            calls.append(1)
            raise AIUnavailable("AI service rejected the API credentials", code="auth")

    token = live_card["public_token"]
    landing = lambda: client.get(f"/api/v1/public/c/{token}", headers=UA).json()  # noqa: E731
    patch_provider(monkeypatch, Down())
    from app.core.config import Settings
    monkeypatch.setattr(Settings, "ai_configured", property(lambda self: True))  # pretend a key is set so the page offers the button at all
    monkeypatch.setattr("app.api.v1.public.privacy.blocked_now", lambda: None)  # the data-terms switch is a separate gate with its own tests
    assert landing()["ai_available"] is True  # offered while the provider is healthy
    body = {"text": "The doctor listened carefully and explained everything.", "language": "auto"}
    r = client.post(f"/api/v1/public/c/{token}/assist", json=body, headers=UA)
    assert r.status_code == 503 and "couldn't improve" in r.json()["detail"] and len(calls) == 1  # the first customer finds out
    assert health.current()["code"] == "auth"
    assert landing()["ai_available"] is False  # the next customer is never offered a button that cannot work
    r2 = client.post(f"/api/v1/public/c/{token}/assist", json=body, headers=UA)
    assert r2.status_code == 503 and "unavailable right now" in r2.json()["detail"] and len(calls) == 1  # and nothing waits on the provider again
    health.reset()
    assert landing()["ai_available"] is True  # and it comes back as soon as the pause ends
    patch_provider(monkeypatch, StubProviderForTests())
    assert client.post(f"/api/v1/public/c/{token}/assist", json=body, headers=UA).status_code == 200  # recovery is automatic once the key works
    assert health.current() is None
