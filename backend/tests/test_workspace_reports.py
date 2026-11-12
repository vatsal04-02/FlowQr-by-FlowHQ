"""Reports, exports, integration status, AI usage and the tenant's own audit log. Google and AI are TEST DOUBLES."""
import csv
import io
import json
from datetime import timedelta

import pytest

from app.core.config import settings
from app.models.base import utcnow
from tests.conftest import owner_exec, owner_query
from tests.test_agent import add_review
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import FakeGoogleProvider, callback, connect, connected  # noqa: F401
from tests.test_location_permissions import invite


def status_of(biz, id_):
    return next(i for i in biz.get("/workspace/integrations").json()["integrations"] if i["id"] == id_)


# ------------------------------------------------------------------ integration honesty
def test_integration_status_never_claims_more_than_is_true(biz_a, monkeypatch):
    items = {i["id"]: i for i in biz_a.get("/workspace/integrations").json()["integrations"]}
    assert items["google"]["status"] == "not_connected" and items["ai"]["status"] == "setup_required" and items["razorpay"]["status"] == "setup_required"
    for k in ("meta", "whatsapp", "rank_provider"):
        assert items[k]["status"] == "setup_required" and items[k]["steps"]
    monkeypatch.setattr(settings, "meta_app_id", "123"), monkeypatch.setattr(settings, "meta_app_secret", "s")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1"), monkeypatch.setattr(settings, "whatsapp_access_token", "t")
    monkeypatch.setattr(settings, "rank_provider", "x"), monkeypatch.setattr(settings, "rank_provider_key", "k")
    for k in ("meta", "whatsapp", "rank_provider"):  # credentials alone never turn into "connected": there is no adapter
        s = status_of(biz_a, k)
        assert s["status"] == "not_available" and "nothing is simulated" in s["detail"]


def test_google_status_follows_what_google_actually_said(connected, fake, gid):
    assert status_of(connected, "google")["status"] == "connected"
    owner_exec("UPDATE google_connections SET api_access = 'awaiting_approval', last_error = 'quota 0' WHERE tenant_id = :t", t=connected.tenant_id)
    assert status_of(connected, "google")["status"] == "setup_required" and "quota 0" in status_of(connected, "google")["detail"]
    owner_exec("UPDATE google_connections SET api_access = 'api_disabled' WHERE tenant_id = :t", t=connected.tenant_id)
    assert status_of(connected, "google")["status"] == "setup_required"
    owner_exec("UPDATE google_connections SET status = 'revoked' WHERE tenant_id = :t", t=connected.tenant_id)
    assert status_of(connected, "google")["status"] == "attention" and "Reconnect" in status_of(connected, "google")["steps"][0]


def test_a_google_account_with_no_locations_is_not_a_working_business_connection(fake, monkeypatch):
    from tests.conftest import make_business
    biz = make_business("Empty Account Co")
    fake.list_locations = lambda at, acct: []  # Google lists the account but it manages nothing
    assert callback(biz, connect(biz, fake)).status_code == 303
    c = biz.get("/google/status").json()["connections"][0]
    assert c["locations_found"] == 0 and c["no_locations"] is True and c["api_access"] == "approved"
    s = status_of(biz, "google")
    assert s["status"] == "attention" and "not a working business connection" in s["detail"] and "connect another Google account" in s["steps"][0]
    biz.post("/agent/plan/run")
    t = next(x for x in biz.get("/agent/tasks").json()["tasks"] if x["kind"] == "connect_google")
    assert t["evidence"]["state"] == "no_locations" and "another Google account" in t["suggested_action"]
    assert biz.get("/agent/health").json()["score"] is None  # nothing is scored off an empty account


# ------------------------------------------------------------------ AI usage + audit log
def test_ai_usage_reports_real_counts_and_the_plan_limit(connected, gid):
    from tests.test_agent import Scripted
    u = connected.get("/workspace/ai-usage").json()
    assert u["used_this_month"] == 0 and u["monthly_limit"] > 0 and u["provider"]["configured"] is False and "limit" in u["note"]


def test_audit_log_is_admin_only_tenant_scoped_and_paged(connected, biz_b):
    connected.put("/agent/settings", json={"daily_plan": True})
    connected.patch("/tenant", json={"brand_tone": "calm"})
    staff = invite(connected)
    assert staff.get("/workspace/audit-log").status_code == 403
    a = connected.get("/workspace/audit-log", params={"limit": 2}).json()
    assert len(a["entries"]) == 2 and a["next_before"] and all(e["by"] for e in a["entries"] if e["action"].startswith("agent."))
    more = connected.get("/workspace/audit-log", params={"limit": 200, "before": a["next_before"]}).json()
    assert all(e["id"] not in {x["id"] for x in a["entries"]} for e in more["entries"])
    assert {"agent.settings"} <= {e["action"] for e in connected.get("/workspace/audit-log", params={"limit": 200}).json()["entries"]}
    assert [e for e in connected.get("/workspace/audit-log", params={"action": "agent."}).json()["entries"] if not e["action"].startswith("agent.")] == []
    assert biz_b.get("/workspace/audit-log").json()["entries"] != connected.get("/workspace/audit-log").json()["entries"]
    assert all(e["action"] != "agent.settings" for e in biz_b.get("/workspace/audit-log", params={"limit": 200}).json()["entries"])


# ------------------------------------------------------------------ reports
def test_report_summary_uses_real_numbers_and_says_when_google_has_not_answered(connected, gid):
    for rating, replied, days in ((5, True, 3), (4, False, 6), (2, False, 8)):
        add_review(connected, gid, rating, "x", days_ago=days, replied=replied)
    r = connected.get("/reports/summary").json()
    assert r["reputation"]["reviews"] == 3 and r["reputation"]["replied"] == 1 and r["reputation"]["average_rating"] == pytest.approx(3.67, abs=0.01) and r["reputation"]["unanswered_now"] == 2
    assert r["reputation"]["distribution"]["5"] == 1 and r["google_performance"]["available"] is False and "Nothing is estimated" in r["google_performance"]["note"]
    assert r["campaigns"]["scans"] == 0 and "ai_activity" in r
    connected.post("/agent/google/refresh")
    g_ = connected.get("/reports/summary").json()["google_performance"]
    assert g_["available"] and g_["locations"][0]["last_28_days"] == 4 and g_["locations"][0]["previous_28_days"] == 13 and g_["locations"][0]["fetched_at"]
    assert connected.get("/reports/summary", params={"from": "2030-01-02", "to": "2030-01-01"}).status_code == 422


def test_csv_exports_neutralise_spreadsheet_formulas_and_are_scoped(connected, gid, biz_b):
    add_review(connected, gid, 1, "=HYPERLINK(\"http://evil.example\",\"click\")", days_ago=2)
    add_review(connected, gid, 5, "+1234 call me", days_ago=2)
    r = connected.get("/reports/export/reviews.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "no-store" in r.headers["cache-control"]
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    texts = {row[4] for row in rows[1:]}
    assert "'=HYPERLINK(\"http://evil.example\",\"click\")" in texts and "'+1234 call me" in texts and rows[0][:4] == ["review_date", "location", "reviewer", "rating"]
    assert list(csv.reader(io.StringIO(biz_b.get("/reports/export/reviews.csv").text.lstrip("﻿")))) [1:] == []
    assert connected.get("/reports/export/secrets.csv").status_code == 404
    staff = invite(connected)
    assert staff.get("/reports/export/reviews.csv").status_code == 200 and staff.get("/reports/export/tasks.csv").status_code == 403 and staff.get("/reports/export/ai.csv").status_code == 403
    assert "ai_activity" not in staff.get("/reports/summary").json()
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'report.csv'", t=connected.tenant_id)[0][0] >= 1


def test_restricted_staff_reports_cover_only_their_location(connected, gid):
    other = connected.post("/locations", json={"name": "Second branch"}).json()["id"]
    add_review(connected, gid, 5, "mine", days_ago=2)
    add_review(connected, gid, 1, "theirs", days_ago=2, loc=other)
    staff = invite(connected, location_ids=[connected.location_id])
    assert staff.get("/reports/summary").json()["reputation"]["reviews"] == 1 and connected.get("/reports/summary").json()["reputation"]["reviews"] == 2
    assert staff.get("/reports/summary").json()["campaigns"] is None
    assert [row[4] for row in csv.reader(io.StringIO(staff.get("/reports/export/reviews.csv").text.lstrip("﻿")))][1:] == ["mine"]
    assert staff.get("/reports/summary", params={"location_id": other}).status_code == 404


def test_pdf_report_is_a_real_pdf_and_states_missing_data(connected, gid):
    add_review(connected, gid, 5, "x", replied=True)
    r = connected.get("/reports/summary.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-1.4") and r.content.rstrip().endswith(b"%%EOF") and r.headers["content-type"] == "application/pdf"
    import zlib, re
    streams = [zlib.decompress(m) for m in re.findall(rb"stream\n(.*?)\nendstream", r.content, re.S)]
    text = b" ".join(streams).decode("latin-1")
    assert "reputation report" in text and "No Google performance data yet" in text and "Page 1 of 1" in text
