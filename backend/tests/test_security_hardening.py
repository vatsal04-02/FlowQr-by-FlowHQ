"""Regression tests for the static-analysis findings fixed in the Google agency release (bandit B613, B324, B314, B608)."""
import pathlib
import re
from types import SimpleNamespace

import pytest

from app.services.sites import hosting

INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_no_python_source_file_contains_an_invisible_or_bidirectional_character():
    """Such characters in source can make code read differently from how it runs ("Trojan Source", bandit B613). Write them as escapes instead."""
    offenders = [f"{p.relative_to(APP)}:{i}" for p in APP.rglob("*.py") for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1) if INVISIBLE.search(line)]
    assert offenders == []


def test_this_test_file_itself_holds_no_invisible_characters():
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert not INVISIBLE.search(text) and chr(0) not in text


def test_the_sanitiser_still_matches_the_characters_it_was_written_to_strip():
    from app.services.sites.service import _INVISIBLE

    for code in (0x200B, 0x200F, 0x202A, 0x202E, 0x2060, 0x206F, 0xFEFF, 0x01, 0x7F):
        assert _INVISIBLE.search("a" + chr(code) + "b"), hex(code)
    assert not _INVISIBLE.search("plain text, digits 123 and Devanagari " + chr(0x0915) + chr(0x094D) + chr(0x0937))


def test_an_oversized_r2_listing_is_refused_before_it_is_parsed():
    provider = object.__new__(hosting.CloudflareProvider)
    provider._r2 = lambda *a, **k: SimpleNamespace(status_code=200, content=b"<x>" + b"a" * (hosting.MAX_LIST_XML_BYTES + 1) + b"</x>")
    with pytest.raises(hosting.HostingError) as e:
        provider._list("sites/")
    assert "unexpectedly large" in str(e.value)


def test_a_normal_r2_listing_still_parses():
    xml = b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Contents><Key>sites/a</Key></Contents><Contents><Key>sites/b</Key></Contents></ListBucketResult>'
    provider = object.__new__(hosting.CloudflareProvider)
    provider._r2 = lambda *a, **k: SimpleNamespace(status_code=200, content=xml)
    assert provider._list("sites/") == ["sites/a", "sites/b"]


def test_the_etag_integrity_check_still_uses_md5_but_not_as_a_security_primitive():
    source = (APP / "services" / "sites" / "hosting.py").read_text(encoding="utf-8")
    assert "usedforsecurity=False" in source
