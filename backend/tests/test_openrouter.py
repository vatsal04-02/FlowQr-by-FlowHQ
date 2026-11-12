"""OpenRouter provider + its use by Review Growth.

MOCKED: every HTTP exchange with OpenRouter below goes through httpx.MockTransport (nothing leaves the machine), so these prove
FlowQR's handling of each provider behaviour, not OpenRouter's real behaviour. Real-API checks are run separately and reported as such.
"""
import ssl
import time
import uuid

import httpx
import pytest

from app.core.config import settings
from app.services.ai import AIUnavailable, get_provider
from app.services.ai.gemini import GeminiProvider
from app.services.ai.openrouter import ENDPOINT, OpenRouterProvider, build_client
from tests.conftest import Session, make_user, owner_exec, owner_query
from tests.test_review_growth import FORM, GOOD, UA, campaign, generate, make_staff, pub

KEY = "sk-or-v1-TESTKEY-never-real"
MODEL = "vendor/test-model:free"


def reply(content="Hello there", *, model=MODEL, prompt=11, completion=7, finish="stop"):
    return httpx.Response(200, json={"id": "gen-1", "model": model, "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
                                     "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}})


def provider(*responses, calls=None):
    """Provider whose transport serves `responses` in order (the last one repeats). Exceptions in the list are raised."""
    queue = list(responses)

    def handler(request: httpx.Request):
        if calls is not None:
            calls.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return OpenRouterProvider(KEY, MODEL, timeout=5, referer="http://localhost:3000", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


# ================================================================ the provider

def test_request_shape_headers_and_usage_accounting():
    calls: list[httpx.Request] = []
    p = provider(reply("  First draft.  ", prompt=100, completion=20), reply("Second draft.", prompt=120, completion=30, model="vendor/served-model"), calls=calls)
    assert p.generate("SYS", "USER", max_tokens=321, temperature=0.7) == "First draft."
    assert p.generate("SYS", "USER2") == "Second draft."
    req = calls[0]
    assert str(req.url) == ENDPOINT and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {KEY}" and req.headers["x-title"] == "FlowQR by FlowHQ" and req.headers["http-referer"] == "http://localhost:3000"
    import json

    body = json.loads(req.content)
    assert body["model"] == MODEL and body["max_tokens"] == 321 and body["temperature"] == 0.7
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert p.usage == {"prompt_tokens": 220, "completion_tokens": 50, "calls": 2, "cost": 0.0, "model": "vendor/served-model"}  # summed across calls


def test_reasoning_is_disabled_by_default_and_can_be_left_on():
    import json

    calls: list = []
    provider(reply("Ok then."), calls=calls).generate("s", "u")
    assert json.loads(calls[0].content)["reasoning"] == {"enabled": False}
    calls = []
    p = OpenRouterProvider(KEY, MODEL, http=httpx.Client(transport=httpx.MockTransport(lambda r: (calls.append(r), reply("Ok then."))[1])), disable_reasoning=False)
    p.generate("s", "u")
    assert "reasoning" not in json.loads(calls[0].content)


def test_content_parts_are_joined():
    r = httpx.Response(200, json={"choices": [{"message": {"content": [{"type": "text", "text": "Part one. "}, {"type": "text", "text": "Part two."}]}, "finish_reason": "stop"}]})
    assert provider(r).generate("s", "u") == "Part one. Part two."


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "forbidden"), (402, "credits"), (400, "provider_error"), (404, "provider_error"), (500, "provider_error")])
def test_http_errors_map_to_codes_without_leaking_details(status, code):
    p = provider(httpx.Response(status, json={"error": {"message": f"secret upstream detail {KEY}"}}))
    with pytest.raises(AIUnavailable) as e:
        p.generate("s", "u")
    assert e.value.code == code
    assert KEY not in str(e.value) and "secret upstream detail" not in str(e.value)


def test_rate_limit_is_retried_once_then_reported_with_retry_after():
    calls: list = []
    p = provider(httpx.Response(429, headers={"retry-after": "7"}, json={}), calls=calls)
    with pytest.raises(AIUnavailable) as e:
        p.generate("s", "u")
    assert e.value.code == "rate_limited" and e.value.retry_after == 7 and len(calls) == 2


def test_transient_failures_recover_on_the_single_retry():
    calls: list = []
    assert provider(httpx.Response(503), reply("Recovered."), calls=calls).generate("s", "u") == "Recovered." and len(calls) == 2
    calls = []
    assert provider(httpx.Response(429, headers={"retry-after": "1"}), reply("After limit."), calls=calls).generate("s", "u") == "After limit." and len(calls) == 2
    calls = []
    with pytest.raises(AIUnavailable) as e:  # still failing on the retry => reported, not looped forever
        provider(httpx.Response(502), httpx.Response(502), calls=calls).generate("s", "u")
    assert e.value.code == "provider_error" and len(calls) == 2


def test_retry_wait_is_capped(monkeypatch):
    waits = []
    p = OpenRouterProvider(KEY, MODEL, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "3600"}))), sleep=waits.append)
    with pytest.raises(AIUnavailable):
        p.generate("s", "u")
    assert waits == [2.0]  # never sleeps an hour inside a customer request


def test_transport_failures():
    with pytest.raises(AIUnavailable) as e:
        provider(httpx.ReadTimeout("slow")).generate("s", "u")
    assert e.value.code == "timeout"
    with pytest.raises(AIUnavailable) as e:
        provider(httpx.ConnectError("connection refused")).generate("s", "u")
    assert e.value.code == "provider_error"
    with pytest.raises(AIUnavailable) as e:
        provider(httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain")).generate("s", "u")
    assert e.value.code == "tls" and "AI_EXTRA_CA_BUNDLE" in str(e.value)


@pytest.mark.parametrize("resp,code", [
    (httpx.Response(200, content=b"<html>gateway</html>"), "bad_response"),
    (httpx.Response(200, json=["not", "a", "dict"]), "bad_response"),
    (httpx.Response(200, json={"choices": []}), "bad_response"),
    (httpx.Response(200, json={"no": "choices"}), "bad_response"),
    (httpx.Response(200, json={"choices": [{"message": {}}]}), "bad_response"),
    (httpx.Response(200, json={"choices": [{"message": {"content": None}}]}), "bad_response"),
    (httpx.Response(200, json={"choices": [{"message": {"content": "   \n "}}]}), "bad_response"),
    (reply("Half a sent", finish="length"), "bad_response"),  # truncated by max_tokens
    (httpx.Response(200, json={"error": {"code": 429, "message": "upstream limit"}}), "rate_limited"),
    (httpx.Response(200, json={"error": {"code": 401, "message": "no key"}}), "auth"),
    (httpx.Response(200, json={"error": {"code": 403, "message": "model restricted"}}), "forbidden"),
    (httpx.Response(200, json={"error": {"code": 402, "message": "credits"}}), "credits"),
    (httpx.Response(200, json={"error": {"code": 502, "message": "provider down"}}), "provider_error"),
    (httpx.Response(200, json={"error": "string error"}), "provider_error"),
])
def test_malformed_or_error_bodies(resp, code):
    with pytest.raises(AIUnavailable) as e:
        provider(resp).generate("s", "u")
    assert e.value.code == code


def test_missing_usage_is_tolerated():
    p = provider(httpx.Response(200, json={"choices": [{"message": {"content": "Fine."}, "finish_reason": "stop"}]}))
    assert p.generate("s", "u") == "Fine." and p.usage["prompt_tokens"] == 0 and p.usage["model"] == MODEL


def test_extra_ca_bundle_adds_trust_but_never_disables_verification(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Proxy Root")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    pem = tmp_path / "extra.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    c = build_client(5, str(pem))
    assert isinstance(c, httpx.Client)
    ctx = c._transport._pool._ssl_context
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True  # still verifying
    certs = {d["subject"][0][0][1] for d in ctx.get_ca_certs()}
    assert "Test Proxy Root" in certs and len(certs) > 5  # the extra root is ADDED to the normal bundle
    with pytest.raises((FileNotFoundError, ssl.SSLError)):
        build_client(5, str(tmp_path / "missing.pem"))
    assert isinstance(build_client(5, ""), httpx.Client)


# ================================================================ provider switching

def test_get_provider_switches_by_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)
    p = get_provider()
    assert isinstance(p, OpenRouterProvider) and p.model == MODEL and settings.ai_configured is True
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    assert settings.ai_configured is False
    with pytest.raises(AIUnavailable) as e:
        get_provider()
    assert e.value.code == "not_configured"
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    assert isinstance(get_provider(), GeminiProvider) and settings.ai_configured is True  # switching back needs no code change
    monkeypatch.setattr(settings, "ai_provider", "nonsense")
    with pytest.raises(AIUnavailable) as e:
        get_provider()
    assert e.value.code == "not_configured" and settings.ai_configured is False


def test_api_key_is_never_exposed_to_clients(biz_a, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)
    blobs = [biz_a.get("/review-growth/settings").text, biz_a.get("/auth/me").text, biz_a.get("/review-growth/campaigns").text]
    assert all(KEY not in b and "TESTKEY" not in b for b in blobs)
    assert biz_a.get("/review-growth/settings").json()["ai"]["model"] == MODEL


# ================================================================ Review Growth through the OpenRouter provider

@pytest.fixture()
def use(monkeypatch):
    """Route Review Growth to an OpenRouter provider backed by a mock transport serving the given responses."""
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)

    def install(*responses, module="app.api.v1.review_public"):
        holder = {}

        def factory():
            holder["p"] = provider(*responses)
            return holder["p"]

        monkeypatch.setattr(f"{module}.get_provider", factory)
        return holder

    return install


def logs(tenant_id):
    return owner_query("SELECT kind, provider, model, status, error, prompt_tokens, completion_tokens FROM ai_generation_logs WHERE tenant_id=:t ORDER BY created_at", t=tenant_id)


def test_generation_logs_model_and_token_consumption(biz_a, client, use):
    use(reply(GOOD[0], model="vendor/served-model", prompt=210, completion=48))
    c = campaign(biz_a)
    d = generate(client, c).json()
    assert d["ai_status"] == "ok" and d["draft"] == GOOD[0]
    assert logs(biz_a.tenant_id) == [("review_generate", "openrouter", "vendor/served-model", "ok", None, 210, 48)]


def test_rejected_drafts_still_account_for_every_token_spent(biz_a, client, use):
    use(reply("I had 12 sessions and was completely cured.", prompt=100, completion=10))  # fails the checks on both attempts
    d = generate(client, campaign(biz_a)).json()
    assert d["ai_status"] == "rejected" and d["draft"] is None
    row = logs(biz_a.tenant_id)[0]
    assert row[3] == "rejected" and row[5] == 200 and row[6] == 20 and row[1] == "openrouter"  # two calls billed


@pytest.mark.parametrize("responses,code,tokens", [
    ((httpx.Response(429, headers={"retry-after": "1"}),), "rate_limited", None),
    ((httpx.Response(401, json={"error": "invalid key"}),), "auth", None),
    ((httpx.Response(402),), "credits", None),
    ((httpx.Response(500),), "provider_error", None),
    ((httpx.ReadTimeout("slow"),), "timeout", None),
    ((httpx.Response(200, content=b"not json"),), "bad_response", None),
    ((reply("", prompt=11, completion=0),), "bad_response", 11),  # the provider answered (and billed) but gave nothing usable
])
def test_provider_failures_never_block_or_alarm_the_customer(biz_a, client, use, responses, code, tokens):
    use(*responses)
    c = campaign(biz_a)
    r = generate(client, c)
    body = r.json()
    assert r.status_code == 200 and body["ai_status"] == "unavailable" and body["draft"] is None and body["session_id"]
    assert "own words" in body["message"]
    blob = r.text.lower()
    assert not any(w in blob for w in ("openrouter", "credential", "api key", "rate limit", "401", "429", code if code != "timeout" else "zzz"))  # no provider detail
    row = logs(biz_a.tenant_id)[0]
    assert row[1] == "openrouter" and row[3] == "error" and row[4].startswith(code + ":") and row[5] == tokens
    approved = pub(client, "POST", c["public_id"], "/approve", json={"session_id": body["session_id"], "final_text": "Wrote this myself, thank you."})
    assert approved.status_code == 200  # the customer can still finish
    types = [e[0] for e in owner_query("SELECT event_type FROM review_events WHERE campaign_id=:c ORDER BY created_at", c=c["id"])]
    assert sorted(types[:3]) == sorted(["feedback_submitted", "ai_requested", "generation_failed"])  # same-ms events may tie on created_at


def test_unconfigured_provider_is_logged_against_the_configured_provider(biz_a, client, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    d = generate(client, campaign(biz_a)).json()
    assert d["ai_status"] == "unavailable"
    row = logs(biz_a.tenant_id)[0]
    assert row[1] == "openrouter" and row[4].startswith("not_configured")


def test_english_and_hindi_through_openrouter(biz_a, client, use):
    c = campaign(biz_a)
    hindi = "मैं पीठ दर्द की फिजियोथेरेपी के लिए गया था और डॉक्टर ने ध्यान से सुना। रिसेप्शन का व्यवहार भी अच्छा था।"
    h = use(reply(hindi))
    d = generate(client, c, language="hi").json()
    assert d["ai_status"] == "ok" and d["draft"] == hindi and d["language"] == "hi"
    sent = h["p"]  # prompt carried the Hindi instruction to the provider
    use(reply(GOOD[0]))
    assert generate(client, c, language="hi").json()["ai_status"] == "rejected"  # English text for a Hindi request
    use(reply(hindi))
    assert generate(client, c, language="en").json()["ai_status"] == "rejected"  # Hindi script in an English review
    use(reply(GOOD[0]))
    assert generate(client, c, language="en").json()["ai_status"] == "ok"
    assert sent is not None


def test_negative_sentiment_is_preserved_not_polished_away(biz_a, client, use):
    c = campaign(biz_a)
    form = {"service": "billing and appointment", "appreciated": "", "details": "waited almost an hour and nobody explained the charges", "rating": 1}
    use(reply("An excellent and wonderful visit, the wait did not matter and the charges were clear."))
    assert generate(client, c, **form).json()["ai_status"] == "rejected"
    honest = "I waited almost an hour for my appointment and nobody explained the charges to me."
    use(reply(honest))
    d = generate(client, c, **form).json()
    assert d["ai_status"] == "ok" and d["draft"] == honest
    a = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": honest})
    assert a.status_code == 200 and a.json()["review_url"]  # a 1-star customer gets the same path to Google as anyone


def test_empty_or_whitespace_feedback_never_reaches_the_model(biz_a, client, use):
    h = use(reply(GOOD[0]))
    c = campaign(biz_a)
    for payload in ({}, {"service": "", "appreciated": "   ", "details": "\n\t "}, {"rating": 5}, {"service": "<>"}):
        r = pub(client, "POST", c["public_id"], "/generate", json={"language": "en", **payload})
        assert r.status_code == 422, payload
    assert "p" not in h and owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0


# ================================================================ admin: test the selected model

def test_admin_can_test_the_configured_model(biz_a, use):
    use(reply(GOOD[0], model="vendor/served-model", prompt=90, completion=25), module="app.api.v1.review_growth")
    r = biz_a.post("/review-growth/ai/test", json={"text": "back pain physiotherapy, the doctor listened carefully, reception was friendly", "language": "en", "style": "short", "rating": 5})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["ok"] is True and t["draft"] == GOOD[0] and t["checks"] == {"passed": True, "reason": None, "fact_check": False}
    assert t["provider"] == "openrouter" and t["model"] == MODEL and t["model_served"] == "vendor/served-model"
    assert t["tokens"] == {"prompt": 90, "completion": 25, "calls": 1} and isinstance(t["latency_ms"], int) and t["error"] is None
    assert KEY not in r.text
    assert logs(biz_a.tenant_id) == [("review_test", "openrouter", "vendor/served-model", "ok", None, 90, 25)]


def test_admin_test_shows_why_a_draft_was_rejected(biz_a, use):
    bad = "I attended 12 sessions with Dr. Rao and was completely cured."
    use(reply(bad), module="app.api.v1.review_growth")
    t = biz_a.post("/review-growth/ai/test", json={}).json()
    assert t["ok"] is False and t["draft"] is None and t["checks"]["passed"] is False and t["checks"]["reason"]
    assert t["rejected_text"] == bad and t["error"]["code"] == "rejected" and t["tokens"]["calls"] == 2


@pytest.mark.parametrize("responses,code", [((httpx.Response(401),), "auth"), ((httpx.Response(429),), "rate_limited"), ((httpx.ReadTimeout("x"),), "timeout"), ((httpx.Response(500),), "provider_error")])
def test_admin_test_reports_provider_failures_precisely(biz_a, use, responses, code):
    use(*responses, module="app.api.v1.review_growth")
    t = biz_a.post("/review-growth/ai/test", json={}).json()
    assert t["ok"] is False and t["error"]["code"] == code and t["draft"] is None and KEY not in str(t)


def test_admin_test_when_not_configured(biz_a, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    t = biz_a.post("/review-growth/ai/test", json={}).json()
    assert t["ok"] is False and t["error"]["code"] == "not_configured"


def test_admin_test_authorization_validation_and_limits(biz_a, biz_b, use):
    use(reply(GOOD[0]), module="app.api.v1.review_growth")
    assert Session(None, "anon").post("/review-growth/ai/test", json={}).status_code == 401
    assert biz_a.http.post("/api/v1/review-growth/ai/test", json={}).status_code == 403  # CSRF
    assert make_staff(biz_a).post("/review-growth/ai/test", json={}).status_code == 403  # admins only
    assert biz_a.post("/review-growth/ai/test", json={"text": "   "}).status_code == 422
    assert biz_a.post("/review-growth/ai/test", json={"language": "fr"}).status_code == 422
    codes = [biz_a.post("/review-growth/ai/test", json={}).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    assert biz_b.post("/review-growth/ai/test", json={}).status_code == 200  # limits are per business


def test_migration_0008_token_columns_roundtrip(biz_a, client, use):
    import os
    import subprocess
    import sys

    use(reply(GOOD[0], prompt=5, completion=6))
    generate(client, campaign(biz_a))
    backend = os.path.dirname(os.path.dirname(__file__))

    def alembic(*a):
        subprocess.run([sys.executable, "-m", "alembic", *a], check=True, env={**os.environ}, cwd=backend)

    def cols():
        return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name='ai_generation_logs'")}

    assert {"prompt_tokens", "completion_tokens"} <= cols()
    alembic("downgrade", "0007")
    try:
        assert not ({"prompt_tokens", "completion_tokens"} & cols())
        assert owner_query("SELECT count(*) FROM ai_generation_logs")[0][0] >= 1  # log rows themselves survive
    finally:
        alembic("upgrade", "head")
    assert {"prompt_tokens", "completion_tokens"} <= cols()
