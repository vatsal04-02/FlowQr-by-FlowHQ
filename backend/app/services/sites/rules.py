"""The rules that decide which names and addresses a business website may use. Pure functions, no database, shared by the API, the renderer and the tests.

Hostname resolution is deliberately narrow: a request host is accepted only if it is `<slug>.<SITES_BASE_DOMAIN>` with exactly one label above the base, that label is a valid, non-reserved slug,
and no X-Forwarded-Host or other header is consulted. Anything else (an IP address, a port abuse, a nested subdomain, a look-alike, punycode) resolves to nothing."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

SLUG_MIN, SLUG_MAX = 3, 40
QUARANTINE_DAYS = 90

# Names that must never become a business website: the product's own hosts and services, anything that looks like infrastructure, authentication or payment, and single characters.
RESERVED_SLUGS = frozenset("""
www api go app apps admin administrator root mail email smtp imap pop pop3 mx ns ns1 ns2 dns ftp sftp ssh vpn cdn static assets asset media files file img image images upload uploads download
blog shop store help support status docs doc dev test testing staging stage prod production demo sandbox preview sites site web website websites flowqr flowhq flowqr-site billing pay payment
payments checkout invoice invoices login logout signin signup register auth oauth sso account accounts dashboard console portal panel webhook webhooks hooks n8n grist clinic review reviews
r q n c s go-live health healthz ready readyz metrics monitor analytics tracking track pixel cname autodiscover autoconfig localhost internal intranet secure security abuse postmaster
hostmaster webmaster noreply no-reply info contact sales team about legal privacy terms cookies cookie robots sitemap favicon null undefined nil none true false
""".split())

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def slug_problem(slug: str | None) -> str | None:
    """Why this is not a usable site name, or None. A name is 3 to 40 characters of a-z, 0-9 and single hyphens, not starting or ending with a hyphen."""
    if not slug or not isinstance(slug, str):
        return "Enter a site name."
    if slug != slug.lower() or slug != slug.strip():
        return "Use lower-case letters, numbers and hyphens only."
    if not (SLUG_MIN <= len(slug) <= SLUG_MAX):
        return f"Use {SLUG_MIN} to {SLUG_MAX} characters."
    if not _LABEL.match(slug):
        return "Use lower-case letters, numbers and hyphens only, and do not start or end with a hyphen."
    if "--" in slug:
        return "Do not use two hyphens in a row."  # also keeps every name out of the xn-- (punycode) space
    if slug.isdigit():
        return "A site name cannot be only numbers."
    if slug in RESERVED_SLUGS:
        return "That name is reserved."
    return None


def suggest_slug(name: str) -> str:
    """A starting point from the business name: 'Sharma Dental Clinic!' -> 'sharma-dental-clinic'. Always a usable name by the rules (never reserved, never too short)."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:SLUG_MAX].strip("-")
    for cand in (base, f"{base[:SLUG_MAX - 5]}-site".strip("-"), f"{base[:SLUG_MAX - 4]}-web".strip("-"), "business-site"):
        if cand and slug_problem(cand) is None:
            return cand
    return "business-site"


def normalise_base(base: str) -> str:
    return (base or "").strip().lower().strip(".")


def hostname_for(slug: str, base: str) -> str:
    return f"{slug}.{normalise_base(base)}"


def slug_from_host(raw: str | None, base: str) -> str | None:
    """The site name a request host stands for, or None. Accepts `slug.base` (optionally with the default port or a trailing dot) and nothing else."""
    if not raw or not isinstance(raw, str) or len(raw) > 253 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
        return None
    host = raw.strip().lower().rstrip(".")
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    base = normalise_base(base)
    if not base or not host.endswith("." + base):
        return None
    label = host[: -(len(base) + 1)]
    if "." in label or slug_problem(label):
        return None
    return label


# ------------------------------------------------------------------------------------------------------------------ links
# Link destinations are an allowlist by purpose. Every link is https; the host must be one of these (or a subdomain of one). Phone and WhatsApp links are built from a validated number, never typed.
LINK_HOSTS = {
    "maps": ("google.com", "google.co.in", "goo.gl", "maps.app.goo.gl", "g.page", "g.co"),
    "review": ("google.com", "g.page", "g.co", "goo.gl", "maps.app.goo.gl", "search.google.com"),
    "social": ("instagram.com", "facebook.com", "fb.com", "fb.me", "youtube.com", "youtu.be", "x.com", "twitter.com", "linkedin.com", "wa.me", "threads.net", "pinterest.com"),
    "order": ("zomato.com", "swiggy.com", "magicpin.in", "dineout.co.in", "eazydiner.com", "ondc.org", "wa.me", "google.com", "g.page", "maps.app.goo.gl", "instagram.com", "facebook.com"),
}


def _host_ok(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in allowed)


def clean_https_url(value: str | None, kind: str, *, max_len: int = 500) -> str | None:
    """An https link to an allowed destination, or None when empty. Raises ValueError with a plain message for anything else (http, javascript:, data:, credentials in the address, an
    unlisted host, whitespace, control characters)."""
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > max_len or any(ord(c) < 33 or ord(c) == 127 for c in v):
        raise ValueError("That link is not valid.")
    parts = urlsplit(v)
    if parts.scheme != "https":
        raise ValueError("Links must start with https://")
    if parts.username or parts.password or not parts.hostname:
        raise ValueError("That link is not valid.")
    host = parts.hostname.lower()
    if not _host_ok(host, LINK_HOSTS[kind]):
        raise ValueError({"maps": "Use a Google Maps link.", "review": "Use the Google review link.", "social": "Use a link to the business's own social page.",
                          "order": "Use a link to a known ordering or booking page."}[kind])
    return v


def digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def tel_href(phone: str | None) -> str | None:
    d = digits(phone)
    if len(d) == 10:
        d = "91" + d
    return f"tel:+{d}" if 11 <= len(d) <= 13 else None


def whatsapp_href(phone: str | None, message: str | None = None) -> str | None:
    from urllib.parse import quote

    d = digits(phone)
    if len(d) == 10:
        d = "91" + d
    if not 11 <= len(d) <= 13:
        return None
    return f"https://wa.me/{d}" + (f"?text={quote(message[:200])}" if message else "")
