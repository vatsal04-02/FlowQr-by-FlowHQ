"""QR rendering. Uses segno (real QR encoding) with error-correction level H and a 4-module quiet zone."""
import io

import segno

from app.core.config import settings

QUIET_ZONE_MODULES = 4  # QR spec minimum


def card_url(public_token: str) -> str:
    base = settings.public_card_base_url.rstrip("/")
    return f"{base}/c/{public_token}"


def campaign_url(public_id: str) -> str:
    """Review Growth campaign landing page. Same base URL as cards, so one short domain serves both."""
    return f"{settings.public_card_base_url.rstrip('/')}/r/{public_id}"


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
