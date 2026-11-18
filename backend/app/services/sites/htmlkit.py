"""A tiny HTML builder that escapes by construction.

Every string handed to `el()` as a child or an attribute value is escaped; only a `Raw` value (produced by this module itself) is passed through unchanged. There is no way to build an element
from business content without escaping it, and tag and attribute names are checked against a fixed list, so a content value can never become markup, an event handler, or a script."""
from __future__ import annotations

import html
import re

TAGS = frozenset("""a article aside body br button caption div dd dl dt em figcaption figure footer form h1 h2 h3 h4 head header hr html img input label li link main meta nav ol option p
section select small span strong table tbody td textarea th thead title tr ul details summary time address abbr""".split())
VOID = frozenset("br hr img input link meta".split())
_ATTR = re.compile(r"^[a-z][a-z0-9-]*$")
# Event-handler attributes (on*) and style are not on this list and are refused. URL-carrying attributes (href, src, action) are checked against _SAFE_URL on every use. aria-* is allowed by pattern.
SAFE_ATTRS = frozenset("""class id lang dir role rel target type name value placeholder required autocomplete inputmode maxlength minlength rows cols for tabindex width height alt loading decoding
fetchpriority sizes colspan scope open method enctype novalidate datetime itemprop itemscope itemtype property charset http-equiv media crossorigin disabled checked selected readonly hidden
href src action content""".split())
_URLISH = {"href", "src", "action"}
_SAFE_URL = re.compile(r"^(?:#[A-Za-z0-9_-]*|/(?!/)[A-Za-z0-9_./%-]*|tel:\+[0-9]{8,15}|mailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+|https://[^\s\"'<>]+|data:image/webp;base64,[A-Za-z0-9+/=]+)$")


class Raw(str):
    """Markup that has already been escaped or built by this module."""


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def text(value) -> Raw:
    return Raw(esc(value))


def _attrs(attrs: dict | None) -> str:
    out = []
    for k, v in (attrs or {}).items():
        k = k.replace("_", "-")
        if v is None or v is False:
            continue
        if not _ATTR.match(k) or k.startswith("on") or not (k in SAFE_ATTRS or re.match(r"^aria-[a-z]+$", k)):
            raise ValueError(f"attribute not allowed: {k}")
        if v is True:
            out.append(k)
            continue
        v = str(v)
        if k in _URLISH and not _SAFE_URL.match(v):
            raise ValueError(f"unsafe URL in {k}")
        out.append(f'{k}="{esc(v)}"')
    return (" " + " ".join(out)) if out else ""


def _flat(children) -> str:
    parts = []
    for c in children:
        if c is None or c is False:
            continue
        if isinstance(c, (list, tuple)):
            parts.append(_flat(c))
        elif isinstance(c, Raw):
            parts.append(str(c))
        else:
            parts.append(esc(c))
    return "".join(parts)


def el(tag: str, attrs: dict | None = None, *children) -> Raw:
    if tag not in TAGS:
        raise ValueError(f"tag not allowed: {tag}")
    a = _attrs(attrs)
    if tag in VOID:
        return Raw(f"<{tag}{a}>")
    return Raw(f"<{tag}{a}>{_flat(children)}</{tag}>")


def raw_style(css: str) -> Raw:
    """A <style> element whose body is OUR css (never business content)."""
    return Raw(f"<style>{css}</style>")


def json_ld(obj: dict) -> Raw:
    """A JSON-LD data block. '<' is escaped so no value can close the block early; the block is data, not script, and is not subject to script-src."""
    import json

    body = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Raw(f'<script type="application/ld+json">{body}</script>')
