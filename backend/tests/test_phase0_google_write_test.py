"""Phase 0: the controlled live-write validation tool (`python -m app.cli google-write-test`).

MOCKED, ALL OF IT. These tests run the tool's real code against a TEST DOUBLE (WriteGoogle) and an httpx.MockTransport. They prove that the tool refuses to
write without explicit authorisation, that it reports a step as passed ONLY when the resource was read back from the (fake) Google and matched, that it
cleans up, and that a Google which says "200 OK" without persisting is reported as FAIL. They are NOT evidence that the real Google API accepts anything:
a live result exists only when the command was run with --execute against an authorised test profile and its report says `"mode": "live"`
(see docs/AGENT_AUDIT.md, "Live Google write results")."""
import argparse
import json
from types import SimpleNamespace

import httpx
import pytest

from app import ops_cli
from app.services import google as g

LOC, TITLE = "locations/777", "FlowQR TEST profile (do not use)"
ORIGINAL = "Original description of the throwaway test profile."
REVIEW = "review-abc"


class WriteGoogle:
    """TEST DOUBLE of the Business Profile surface the tool touches. `calls` records every write so a refused run can be shown to have sent nothing."""

    def __init__(self):
        self.calls = []
        self.description, self.posts, self.media, self.reply = ORIGINAL, [], [], None
        self.lose_posts = self.ignore_update = self.restore_fails = self.reject_reply = self.keep_reply_on_delete = False

    # reads
    def list_accounts(self, at):
        return [SimpleNamespace(name="accounts/1")]

    def list_locations(self, at, account):
        return [SimpleNamespace(name=LOC)]

    def get_location_details(self, at, loc):
        return {"title": TITLE, "description": self.description}

    def list_posts(self, at, acct, loc):
        return list(self.posts)

    def list_media(self, at, acct, loc):
        return list(self.media)

    def get_media(self, at, name):
        if not any(m["name"] == name for m in self.media):
            raise g.GoogleAPIError(404, "not found")
        return next(m for m in self.media if m["name"] == name)

    def list_reviews(self, at, acct, loc, token=None):
        rv = SimpleNamespace(external_id=REVIEW, reply_text=self.reply, reply_state=("REJECTED" if (self.reply and self.reject_reply) else "APPROVED" if self.reply else None),
                             reply_policy_violation="OFFENSIVE" if self.reject_reply else None)
        return SimpleNamespace(reviews=[rv], next_page_token=None)

    # writes
    def create_post(self, at, acct, loc, post):
        self.calls.append("create_post")
        p = {"name": f"{acct}/{loc}/localPosts/1", "summary": post["summary"], "state": "LIVE"}
        if not self.lose_posts:
            self.posts.append(p)
        return p

    def delete_post(self, at, name):
        self.calls.append("delete_post")
        self.posts = [p for p in self.posts if p["name"] != name]

    def upload_media_bytes(self, at, acct, loc, data, ct, category, description=None):
        self.calls.append("upload_media")
        m = {"name": f"{acct}/{loc}/media/1", "category": category, "google_url": None}
        self.media.append(m)
        return m

    def delete_media(self, at, name):
        self.calls.append("delete_media")
        self.media = [m for m in self.media if m["name"] != name]

    def update_location(self, at, loc, changes):
        self.calls.append("update_location")
        new = changes["description"]
        if self.restore_fails and new == ORIGINAL:
            return {"title": TITLE, "description": self.description}  # Google "accepts" but the old test text stays
        if not self.ignore_update:
            self.description = new
        return {"title": TITLE, "description": self.description}

    def reply_to_review(self, at, acct, loc, review_id, comment):
        self.calls.append("reply")
        self.reply = comment
        return {"comment": comment, "state": "REJECTED" if self.reject_reply else "APPROVED"}

    def delete_reply(self, at, acct, loc, review_id):
        self.calls.append("delete_reply")
        if not self.keep_reply_on_delete:
            self.reply = None


def args(**over):
    base = dict(connection=None, location=LOC, post=False, photo=False, profile=False, reply_review=None, reply_text=None, keep_reply=False, execute=True,
                confirm_location=LOC, confirm_title=TITLE, report=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def authorised(monkeypatch):
    monkeypatch.setenv(ops_cli.LIVE_ENV, LOC)


def run(a, fake, **kw):
    return ops_cli.google_write_test(a, provider=fake, access_token="mock-token", sleep=lambda s: None, **kw)


ALL = dict(post=True, photo=True, profile=True, reply_review=REVIEW, reply_text="Thank you for visiting. This is a connection test reply.")


# ============================================================================ 1. authorisation guards: refusals send nothing

def test_a_dry_run_sends_nothing(capsys):
    f = WriteGoogle()
    assert run(args(execute=False, **ALL), f) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "NOT EXECUTED" in out and "MOCKED PROVIDER" in out and f.calls == []


@pytest.mark.parametrize("over,why", [
    (dict(confirm_location="locations/999"), "--confirm-location must repeat"),
    (dict(confirm_title="Some other profile"), "--confirm-title must repeat that title exactly"),
    (dict(confirm_title=None), "--confirm-title must repeat that title exactly"),
])
def test_every_missing_confirmation_refuses_before_any_write(over, why, capsys):
    f = WriteGoogle()
    assert run(args(**ALL, **over), f) == 2 and why in capsys.readouterr().out and f.calls == []


def test_without_the_environment_authorisation_nothing_is_sent(monkeypatch, capsys):
    monkeypatch.delenv(ops_cli.LIVE_ENV)
    f = WriteGoogle()
    assert run(args(**ALL), f) == 2 and ops_cli.LIVE_ENV in capsys.readouterr().out and f.calls == []
    monkeypatch.setenv(ops_cli.LIVE_ENV, "locations/1")  # authorising a DIFFERENT location does not authorise this one
    assert run(args(**ALL), f) == 2 and f.calls == []


def test_the_tool_needs_at_least_one_step_and_a_reply_text(capsys):
    assert run(args(), WriteGoogle()) == 2
    assert run(args(reply_review=REVIEW), WriteGoogle()) == 2 and "--reply-text is required" in capsys.readouterr().out


# ============================================================================ 2. a passing run: every write read back, every write cleaned up

def test_all_four_writes_are_verified_by_reading_back_and_then_cleaned_up(tmp_path, capsys):
    f, report = WriteGoogle(), tmp_path / "report.json"
    assert run(args(report=str(report), **ALL), f) == 0
    out = capsys.readouterr().out
    assert "RESULT: all executed steps passed AND were read back from Google" in out and "[MOCKED: not evidence about Google]" in out
    assert f.calls == ["create_post", "delete_post", "upload_media", "delete_media", "update_location", "update_location", "reply", "delete_reply"]
    assert (f.posts, f.media, f.description, f.reply) == ([], [], ORIGINAL, None)  # the test profile is exactly as it was found
    rep = json.loads(report.read_text())
    assert rep["mode"] == "mocked" and rep["failed"] == 0 and "NOT evidence" in rep["note"]  # a mocked run can never be mistaken for a live one
    steps = {r["step"]: r for r in rep["results"]}
    assert len(steps) == 8 and all(r["status"] == "PASS" and r["verified_by_read_back"] for r in steps.values())


def test_keep_reply_leaves_the_reply_published_on_purpose():
    f = WriteGoogle()
    assert run(args(reply_review=REVIEW, reply_text="A reply that is kept.", keep_reply=True), f) == 0
    assert f.reply == "A reply that is kept." and "delete_reply" not in f.calls


# ============================================================================ 3. a "200 OK" that is not real is a FAIL

def test_a_post_google_accepted_but_does_not_list_is_a_failure_and_never_claims_success(capsys):
    f = WriteGoogle()
    f.lose_posts = True
    assert run(args(post=True), f) == 1
    out = capsys.readouterr().out
    assert "does not list the post that create returned" in out and "FAIL" in out and "all executed steps passed" not in out


def test_a_profile_update_that_is_not_persisted_is_a_failure(capsys):
    f = WriteGoogle()
    f.ignore_update = True
    assert run(args(profile=True), f) == 1
    out = capsys.readouterr().out
    assert "does not show the new description" in out and f.description == ORIGINAL


def test_a_restore_that_does_not_stick_is_reported_loudly_so_the_profile_is_fixed_by_hand(capsys):
    f = WriteGoogle()
    f.restore_fails = True
    assert run(args(profile=True), f) == 1
    assert "ORIGINAL description is not back; restore it by hand" in capsys.readouterr().out


def test_a_reply_google_rejected_is_a_failure():
    f = WriteGoogle()
    f.reject_reply = True
    assert run(args(reply_review=REVIEW, reply_text="A reply Google moderates away."), f) == 1


def test_a_reply_that_is_still_shown_after_delete_is_a_failure(capsys):
    f = WriteGoogle()
    f.keep_reply_on_delete = True
    assert run(args(reply_review=REVIEW, reply_text="A reply that cannot be removed."), f) == 1
    assert "still shown after delete" in capsys.readouterr().out


# ============================================================================ 4. the provider call and the CLI wiring

def test_delete_reply_sends_the_documented_request(monkeypatch):
    seen = []
    monkeypatch.setattr("app.services.google.provider.settings.google_client_id", "x")
    monkeypatch.setattr("app.services.google.provider.settings.google_client_secret", "y")
    p = g.HttpGoogleProvider(transport=httpx.MockTransport(lambda req: seen.append((req.method, str(req.url), req.headers["authorization"])) or httpx.Response(200, json={})))
    p.delete_reply("tok", "accounts/1", "locations/2", "R1")
    assert seen == [("DELETE", "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/reviews/R1/reply", "Bearer tok")]


def test_the_command_exposes_the_new_flags():
    ap = argparse.ArgumentParser()
    ops_cli.add_commands(ap.add_subparsers(dest="cmd"))
    a = ap.parse_args(["google-write-test", "--location", LOC, "--post", "--profile", "--confirm-title", "T", "--report", "r.json", "--keep-reply"])
    assert (a.profile, a.keep_reply, a.confirm_title, a.report, a.execute) == (True, True, "T", "r.json", False)
