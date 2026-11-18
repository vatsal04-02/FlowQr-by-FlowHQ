"""A review campaign's address belongs to the website, not to the card redirect domain.

Found when PUBLIC_CARD_BASE_URL was switched to https://go.flowqr.site on production: campaign links, QR downloads and message links came out as go.flowqr.site/r/<id>, and that host only serves
/q, /n and /c (everything else goes to the home page), so every new campaign link would have been dead."""
from app.core.config import settings
from app.services import qr
from tests.conftest import make_business
from tests.test_qr import campaign


def test_campaign_addresses_follow_the_website_while_cards_follow_the_redirect_domain(monkeypatch):
    monkeypatch.setattr(settings, "public_card_base_url", "https://go.test.flowqr.example")
    monkeypatch.setattr(settings, "frontend_url", "https://app.test.flowqr.example")
    assert qr.campaign_url("abc123") == "https://app.test.flowqr.example/r/abc123"
    assert qr.card_url("T" * 24, "q") == f"https://go.test.flowqr.example/q/{'T' * 24}" and qr.card_nfc_url("T" * 24) == f"https://go.test.flowqr.example/n/{'T' * 24}"


def test_with_one_domain_for_both_the_address_is_exactly_what_it_always_was(monkeypatch):
    monkeypatch.setattr(settings, "public_card_base_url", "https://flowqr.site")  # production before go.flowqr.site: one base for both
    monkeypatch.setattr(settings, "frontend_url", "https://flowqr.site")
    assert qr.campaign_url("abc123") == "https://flowqr.site/r/abc123"  # identical to the old rule, so every campaign link and printed code stays valid


def test_the_api_hands_businesses_the_website_address_for_their_campaigns_in_every_place(monkeypatch):
    monkeypatch.setattr(settings, "public_card_base_url", "https://go.test.flowqr.example")
    monkeypatch.setattr(settings, "frontend_url", "https://app.test.flowqr.example")
    biz = make_business()
    c = campaign(biz)
    assert c["url"] == f"https://app.test.flowqr.example/r/{c['public_id']}" and "go.test" not in str(c)
    listed = biz.get("/review-growth/campaigns").json()
    assert all("go.test" not in str(x) for x in listed) and any(x["url"].startswith("https://app.test.flowqr.example/r/") for x in listed)
