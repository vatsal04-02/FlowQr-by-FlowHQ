import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict

LANGUAGES = {"en", "hi", "hinglish"}

# Hosts a Google review link may point to. Prevents the public landing page from being used
# as an open redirect / phishing hop.
GOOGLE_REVIEW_HOST_SUFFIXES = (
    "google.com", "google.co.in", "g.page", "goo.gl", "g.co", "maps.app.goo.gl", "page.link",
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def normalize_phone(value: str | None) -> str | None:
    """Normalise to Indian format `+91 98765 43210` where possible; otherwise keep E.164-ish."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and not digits.startswith("91"):
        if 8 <= len(digits) <= 15:
            return "+" + digits
        raise ValueError("Enter a valid phone number")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91 {digits[:5]} {digits[5:]}"
    raise ValueError("Enter a valid 10-digit Indian mobile number (e.g. 98765 43210)")


def validate_timezone(value: str) -> str:
    if value not in available_timezones():
        raise ValueError("Unknown time zone")
    ZoneInfo(value)
    return value


def validate_language(value: str) -> str:
    if value not in LANGUAGES:
        raise ValueError("Language must be one of: en, hi, hinglish")
    return value


def validate_google_review_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Review link must be a secure https:// Google link")
    host = parsed.hostname.lower()
    if not any(host == s or host.endswith("." + s) for s in GOOGLE_REVIEW_HOST_SUFFIXES):
        raise ValueError("Review link must be a Google link (e.g. https://g.page/r/.../review)")
    return url
