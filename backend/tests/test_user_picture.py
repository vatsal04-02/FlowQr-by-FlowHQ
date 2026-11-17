"""The Google account photo: only a Google-hosted https link is ever kept, it is refreshed at each Google sign-in (and cleared when Google sends none), and the app's /auth/me returns it.
Real application and PostgreSQL; nothing talks to Google."""
import pytest

from app.services.google.login import GoogleIdentity, safe_picture
from tests.conftest import make_user, owner_exec, owner_query

GOOD = "https://lh3.googleusercontent.com/a/ACg8ocKexample=s96-c"


@pytest.mark.parametrize("url", [GOOD, "https://lh3.googleusercontent.com/a-/AOh14Gexample", "https://lh4.googleusercontent.com/x", "https://googleusercontent.com/x"])
def test_a_google_hosted_https_link_is_kept(url):
    assert safe_picture(url) == url


@pytest.mark.parametrize("url", [
    None, "", 123, "http://lh3.googleusercontent.com/a", "https://evil.example/a.png", "https://googleusercontent.com.evil.example/a", "https://evil.example/?u=lh3.googleusercontent.com",
    "https://user:pw@lh3.googleusercontent.com/a", "https://lh3.googleusercontent.com:8443/a", "data:image/png;base64,AAAA", "javascript:alert(1)", "//lh3.googleusercontent.com/a", "https://lh3.googleusercontent.com/" + "a" * 500,
])
def test_anything_else_is_dropped(url):
    assert safe_picture(url) is None


def test_identity_carries_no_picture_by_default():
    assert GoogleIdentity(sub="s", email="a@b.example", email_verified=True, name="A").picture is None


def test_me_returns_the_stored_picture_and_null_for_everyone_else():
    a, b = make_user(), make_user()
    owner_exec("UPDATE users SET picture_url = :u WHERE email = :e", u=GOOD, e=a.email)
    for sess, want in [(a, GOOD), (b, None)]:
        r = sess.http.post("/api/v1/auth/login", json={"email": sess.email, "password": sess.password})
        assert r.status_code == 200, r.text
        sess.csrf = r.json().get("csrf_token", sess.csrf)
        assert sess.get("/auth/me").json()["user"]["picture_url"] == want


def test_the_column_exists_and_is_nullable_text_of_500():
    row = owner_query("SELECT is_nullable, character_maximum_length FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'picture_url'")
    assert [tuple(r) for r in row] == [("YES", 500)]
