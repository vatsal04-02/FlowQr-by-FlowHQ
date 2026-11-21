"""QR rendering. Uses segno (real QR encoding) with error-correction level H and a 4-module quiet zone."""
import io

import segno

from app.core.config import settings

QUIET_ZONE_MODULES = 4  # QR spec minimum


def card_url(public_token: str, path: str = "c") -> str:
    """The address a card's printed QR encodes. `path` is the card's own `qr_path`: 'c' for every card printed before inventory
    batches existed (their paper says /c/), 'q' for new ones. Both resolve to the same card."""
    base = settings.public_card_base_url.rstrip("/")
    return f"{base}/{path}/{public_token}"


def card_qr_url(card) -> str:
    """What THIS card's printed QR encodes. Never changes for a card: it is what is on paper."""
    return card_url(card.public_token, card.qr_path or "c")


def card_nfc_url(public_token: str) -> str:
    """The address to write onto this card's NFC tag as an NDEF URL record. Same card as the QR; the channel is recorded as 'nfc'."""
    return f"{settings.public_card_base_url.rstrip('/')}/n/{public_token}"


_TEMPORARY_HOST_PARTS = (
    "localhost", "127.", "0.0.0.0", "::1", ".local", ".localhost",  # nosec B104 - host names a public card address must not use; nothing here binds a socket
    ".internal", ".lan", "ngrok", "trycloudflare.com", "loca.lt", "localtunnel",
    "serveo", "tunnelmole", "lhr.life", "pinggy", "ts.net", "devtunnels", "nip.io", "sslip.io", "cloudflareaccess",
)


def permanent_url_problem(base: str | None = None) -> str | None:
    """Why `base` must not be printed on anything physical, or None if it is a permanent public HTTPS domain.
    A QR or NFC tag that points at localhost, a bare IP or a temporary tunnel stops working the moment that address does."""
    from urllib.parse import urlsplit

    base = (base if base is not None else settings.public_card_base_url).strip()
    parts = urlsplit(base)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return "The public address for cards is not HTTPS. Printed codes must use a permanent https:// domain."
    if not host or "." not in host:
        return "The public address for cards has no real domain name. Printed codes need a permanent public domain."
    if all(c.isdigit() or c == "." for c in host):
        return "The public address for cards is a bare IP address. Printed codes need a permanent domain name."
    if any(m in host for m in _TEMPORARY_HOST_PARTS):
        return f"The public address for cards ({host}) is a local or temporary address. Set PUBLIC_CARD_BASE_URL to your permanent HTTPS domain before printing."
    return None


def campaign_url(public_id: str) -> str:
    """Review Growth campaign landing page. It is a page of the APP, served by the website, so its address follows FRONTEND_URL and NOT the card redirect domain: the redirect domain
    (go.flowqr.site) carries only /q, /n and /c and sends everything else to the home page, so a campaign link built on it would be dead. While the two settings are the same (the
    default, and production before go.flowqr.site) this is exactly the address campaigns have always had."""
    return f"{settings.frontend_url.rstrip('/')}/r/{public_id}"


def _qr(url: str):
    return segno.make(url, error="h", micro=False)


def qr_png(url: str, scale: int = 12) -> bytes:
    buf = io.BytesIO()
    _qr(url).save(buf, kind="png", scale=scale, border=QUIET_ZONE_MODULES, dark="#111827", light="#ffffff")
    return buf.getvalue()


def qr_svg(url: str, scale: int = 10) -> bytes:
    buf = io.BytesIO()
    _qr(url).save(buf, kind="svg", scale=scale, border=QUIET_ZONE_MODULES, dark="#111827", light="#ffffff",
                  xmldecl=False, svgns=True, nl=False)
    return buf.getvalue()
