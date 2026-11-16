"""Go-live operator commands: preflight, set-admin-password and the guarded live Google write test.
Google is a test double: these tests prove the safety rails (dry run by default, explicit confirmation, cleanup, no secrets printed), not Google itself."""
import argparse

import pytest
from fastapi.testclient import TestClient

from app import ops_cli
from app.core.config import settings
from app.services import google as g
from tests.test_gbp import FakeGbpProvider


def ns(**kw):
    base = dict(smtp_test=None, sentry_test=False, email=None, connection=None, location="locations/222", post=False, photo=False, reply_review=None, reply_text=None,
                execute=False, confirm_location=None, profile=False, keep_reply=False, confirm_title=None, report=None)
    base.update(kw)
    return argparse.Namespace(**base)


# ------------------------------------------------------------------ preflight
def test_preflight_in_development_warns_but_does_not_block(capsys, monkeypatch):
    from app.services import ops
    monkeypatch.setattr(ops, "_redis", lambda: object())  # the test suite has no Redis; a missing Redis is its own FAIL (next test)
    assert ops_cli.preflight(ns()) == 0
    out = capsys.readouterr().out
    assert "database" in out and "migrations" in out and "TOKEN_ENCRYPTION_KEY" in out and "MANUAL" in out
    assert "passed" in out and "need you (manual)" in out


def test_preflight_fails_a_production_boot_with_unsafe_settings_and_never_prints_secrets(capsys, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"), monkeypatch.setattr(settings, "smtp_port", 1)
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret-xyz"), monkeypatch.setattr(settings, "smtp_user", "u")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    from app.services import ops
    monkeypatch.setattr(ops, "_redis", lambda: None)
    assert ops_cli.preflight(ns()) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "NOT READY" in out and "SMTP login" in out
    assert "smtp-secret-xyz" not in out and settings.secret_key not in out and settings.token_encryption_key not in out


def test_preflight_smtp_test_message_goes_through_the_mailer(capsys, monkeypatch):
    from app.services import mailer
    mailer.OUTBOX.clear()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"), monkeypatch.setattr(settings, "smtp_port", 1)
    ops_cli.preflight(ns(smtp_test="owner@example.com"))
    assert [m["to"] for m in mailer.OUTBOX] == ["owner@example.com"] and "FlowQR email test" in mailer.OUTBOX[0]["subject"]


# ------------------------------------------------------------------ set-admin-password
def _answers(monkeypatch, *pw):
    it = iter(pw)
    monkeypatch.setattr(ops_cli.getpass, "getpass", lambda prompt="": next(it))


def _login(email, password):
    from app.main import app
    return TestClient(app, base_url="http://testserver").post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def test_admin_password_change_works_ends_every_session_and_audits(admin, monkeypatch, capsys):
    assert admin.get("/admin/ops").status_code == 200  # signed in
    _answers(monkeypatch, "Brand-New-Pass-77", "Brand-New-Pass-77")
    assert ops_cli.set_admin_password(ns(email="ROOT@flowhq-admin.example.com")) == 0
    out = capsys.readouterr().out
    assert "Brand-New-Pass-77" not in out and "session(s) were ended" in out
    assert admin.get("/admin/ops").status_code == 401  # the old session no longer works
    assert _login("root@flowhq-admin.example.com", "Brand-New-Pass-77") == 200
    assert _login("root@flowhq-admin.example.com", admin.password) == 401  # the old password is dead
    # leave the shared admin fixture usable for later tests
    _answers(monkeypatch, admin.password, admin.password)
    assert ops_cli.set_admin_password(ns(email="root@flowhq-admin.example.com")) == 0


def test_admin_password_rejects_weak_mismatched_and_non_admin(admin, biz_a, monkeypatch, capsys):
    _answers(monkeypatch, "short", "short")
    assert ops_cli.set_admin_password(ns(email="root@flowhq-admin.example.com")) == 1 and "at least 10" in capsys.readouterr().out
    _answers(monkeypatch, "Another-Strong-Pass-1", "Different-Strong-Pass-2")
    assert ops_cli.set_admin_password(ns(email="root@flowhq-admin.example.com")) == 1 and "differ" in capsys.readouterr().out
    assert ops_cli.set_admin_password(ns(email=biz_a.email)) == 1  # ordinary owners are not touched by the admin tool
    assert _login("root@flowhq-admin.example.com", admin.password) == 200  # nothing changed


# ------------------------------------------------------------------ guarded live write test
class WriteProbe(FakeGbpProvider):
    def __init__(self):
        super().__init__()
        self.calls, self.deleted = [], []

    def refresh_access_token(self, rt):
        from app.services.google.provider import TokenSet
        self.calls.append("refresh")
        return TokenSet("at", 3600)

    def list_accounts(self, at):
        from app.services.google.provider import GAccount
        return [GAccount("accounts/111", "Clinic")]

    def list_locations(self, at, acct):
        from app.services.google.provider import GLocation
        return [GLocation(acct, "locations/222", "Test", "x", "P", None)]

    def create_post(self, at, acct, loc, post):
        self.calls.append("create_post")
        return super().create_post(at, acct, loc, post)

    def delete_post(self, at, name):
        self.calls.append("delete_post")
        super().delete_post(at, name)

    def upload_media_bytes(self, at, acct, loc, data, ctype, category, description=None):
        self.calls.append("upload")
        assert ctype == "image/png" and data[:4] == b"\x89PNG"
        m = {"name": f"{acct}/{loc}/media/9", "google_url": None}
        self.media.append(m)
        return m

    def get_media(self, at, name):
        return {"name": name, "google_url": "https://lh3.example/x"}

    def delete_media(self, at, name):
        self.calls.append("delete_media")
        super().delete_media(at, name)


@pytest.fixture()
def probe(monkeypatch):
    p = WriteProbe()
    monkeypatch.setattr(g, "get_google_provider", lambda: p)
    monkeypatch.setenv("GOOGLE_SMOKE_REFRESH_TOKEN", "rt-test")
    return p


def test_the_write_test_is_a_dry_run_by_default_and_sends_nothing(probe, capsys):
    assert ops_cli.google_write_test(ns(post=True, photo=True, reply_review="r1", reply_text="Thanks")) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "NOT EXECUTED" in out and "DELETE it" in out and "PUBLIC" in out
    assert probe.calls == [] and probe.posts == [] and probe.media == []


def test_execute_needs_the_location_repeated_and_choosing_a_step(probe, capsys):
    assert ops_cli.google_write_test(ns(post=True, execute=True)) == 2 and "Refused" in capsys.readouterr().out
    assert ops_cli.google_write_test(ns(post=True, execute=True, confirm_location="locations/999")) == 2
    assert ops_cli.google_write_test(ns()) == 2
    assert ops_cli.google_write_test(ns(reply_review="r1")) == 2  # a reply needs its text
    assert probe.calls == []


def authorise(monkeypatch):
    """Phase 0: a live write needs three deliberate confirmations: the env var, --confirm-location and --confirm-title (the title Google returns: "Clinic" for this double)."""
    monkeypatch.setenv(ops_cli.LIVE_ENV, "locations/222")
    return dict(execute=True, confirm_location="locations/222", confirm_title="Clinic")


def test_a_confirmed_run_creates_checks_and_removes_the_test_post_and_photo(probe, capsys, monkeypatch):
    assert ops_cli.google_write_test(ns(post=True, photo=True, **authorise(monkeypatch)), sleep=lambda s: None) == 0
    out = capsys.readouterr().out
    assert probe.calls.count("create_post") == 1 and probe.calls.count("delete_post") == 1 and probe.calls.count("upload") == 1 and probe.calls.count("delete_media") == 1
    assert probe.posts == [] and probe.media == []  # nothing left behind on the "Google" side
    assert "rt-test" not in out and "at" not in out.split("Google")[0]


def test_a_failed_google_step_is_reported_as_failure_not_success(probe, capsys, monkeypatch):
    kw = authorise(monkeypatch)
    probe.error = None
    # the title read happens before any write, so the injected Google error is raised on the first WRITE (create_post) only
    def denied(at, acct, loc, post):
        raise g.GoogleAPIError(403, "denied")
    probe.create_post = denied
    assert ops_cli.google_write_test(ns(post=True, **kw), sleep=lambda s: None) == 1
    assert "FAIL" in capsys.readouterr().out
