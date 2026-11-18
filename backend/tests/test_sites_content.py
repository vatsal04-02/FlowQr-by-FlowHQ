"""Website builder, pure logic: names and hostnames, links, the content validator, the publish check, the six templates, and rendering (escaping, SEO, no JavaScript, determinism).
No database: these run in a second."""
import json
import re
import uuid
from html.parser import HTMLParser

import pytest

from app.services.sites import catalog as C
from app.services.sites import content as CT
from app.services.sites import render as R
from app.services.sites import rules
from app.services.sites.htmlkit import el, json_ld

BASE = "flowqr.site"
BIZ = {"name": "Sharma Physio", "category": "Physiotherapy clinic", "city": "Kanpur", "phone": "+91 98765 43210", "email": "hello@sharma.example", "address": "12 Mall Road, Kanpur"}
XSS = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "'; DROP TABLE sites;--", "</script><script>alert(2)</script>", "<svg onload=alert(3)>", "javascript:alert(4)", "{{7*7}}", "${7*7}"]
ID = lambda: str(uuid.uuid4())  # noqa: E731


def valid(key="clinic", biz=None):
    c = C.default_content(key, biz or BIZ)
    clean, errs = CT.validate_content(c, key, set())
    assert not errs, errs
    return clean


def build(clean, key, assets=None, preview=False):
    return R.build_site(clean, key, host=f"sharma.{BASE}", assets=assets or {}, retention_days=180, preview=preview)


def fill_strings(x, payload):
    """Put `payload` into every free-text value (not into ids, enums, urls, phones or booleans), to prove nothing is ever interpreted as markup."""
    if isinstance(x, dict):
        return {k: (fill_strings(v, payload) if k not in ("id", "type", "kind", "enabled", "veg", "day", "open", "close", "closed", "accent", "phone", "whatsapp", "email", "maps_url", "review_url", "order_url",
                                                         "instagram", "facebook", "youtube", "image", "logo", "og_image", "asset", "show_enquiry", "valid_until") else v) for k, v in x.items()}
    if isinstance(x, list):
        return [fill_strings(i, payload) for i in x] if x and not isinstance(x[0], str) else ([payload] * max(len(x), 1))
    if isinstance(x, str):
        return payload
    return x


def complete(c, key):
    """Give every enabled section real content and the business opening hours, so the site passes the publish check (galleries are switched off: they need uploaded images)."""
    for s in c["sections"]:
        for f in C.SECTION_TYPES[s["type"]]["fields"]:
            if f["kind"] in ("text", "textarea"):
                s["data"][f["key"]] = s["data"][f["key"]] or "Sample text"
            elif f["kind"] == "strings":
                s["data"][f["key"]] = ["One", "Two"]
            elif f["kind"] == "list":
                item = {}
                for sub in f["fields"]:
                    if sub["kind"] == "list":
                        item[sub["key"]] = [{g["key"]: ("veg" if g["key"] == "veg" else "x") for g in sub["fields"]}]
                    else:
                        item[sub["key"]] = "Sample" if sub["kind"] in ("text", "textarea") else sub["options"][-1] if sub["kind"] == "select" else None
                s["data"][f["key"]] = [item]
        if s["type"] == "gallery":
            s["enabled"] = False
    c["business"]["hours"] = [{"day": d, "closed": d == "Sunday", "open": "" if d == "Sunday" else "09:00", "close": "" if d == "Sunday" else "18:00"} for d in C.DAYS]
    clean, errs = CT.validate_content(c, key, set())
    assert not errs, errs
    return clean


def filled(key="clinic"):
    """Every list has content, so every section renders."""
    return complete(valid(key), key)


# ---------------------------------------------------------------------------------------------------------------- names
@pytest.mark.parametrize("slug", ["sharma", "citysalon", "geetakrishna", "royal-salon", "a1b", "x" * 40, "sharma-dental-2"])
def test_valid_site_names(slug):
    assert rules.slug_problem(slug) is None


@pytest.mark.parametrize("slug", ["", None, "ab", "x" * 41, "Sharma", " sharma", "sharma ", "-sharma", "sharma-", "a--b", "xn--abc", "12345", "sha_rma", "sha.rma", "shärma", "sharma/", "sharma\n", "a b c"])
def test_invalid_site_names(slug):
    assert rules.slug_problem(slug)


@pytest.mark.parametrize("slug", ["www", "api", "app", "admin", "mail", "smtp", "cdn", "static", "login", "auth", "billing", "flowqr", "flowhq", "n8n", "grist", "support", "status", "blog", "demo"])
def test_reserved_names_are_refused(slug):
    assert rules.slug_problem(slug) == "That name is reserved."


def test_go_is_reserved_for_qr_and_nfc_redirects():
    assert "go" in rules.RESERVED_SLUGS and rules.slug_problem("go") and rules.slug_from_host("go.flowqr.site", BASE) is None
    assert all(rules.slug_problem(x) for x in ("go", "r", "q", "n", "c", "s"))  # the QR, NFC and review doors are also too short to ever be a site name


def test_suggestion_from_a_business_name():
    assert rules.suggest_slug("Sharma Dental Clinic!") == "sharma-dental-clinic"
    assert rules.suggest_slug("  Royal   Salon & Spa ") == "royal-salon-spa"
    assert rules.slug_problem(rules.suggest_slug("A")) is None and rules.slug_problem(rules.suggest_slug("***")) is None
    assert len(rules.suggest_slug("x" * 200)) <= 40


# ---------------------------------------------------------------------------------------------------------------- hostnames
@pytest.mark.parametrize("host,expect", [("sharma.flowqr.site", "sharma"), ("SHARMA.FlowQR.site", "sharma"), ("sharma.flowqr.site:443", "sharma"), ("sharma.flowqr.site.", "sharma"), ("royal-salon.flowqr.site", "royal-salon")])
def test_hosts_that_resolve(host, expect):
    assert rules.slug_from_host(host, BASE) == expect


@pytest.mark.parametrize("host", [None, "", "flowqr.site", "www.flowqr.site", "api.flowqr.site", "go.flowqr.site", "a.b.flowqr.site", "sharma.flowqr.site.evil.com", "evilflowqr.site", "sharma.evil.com",
                                  "sharma.flowqr.site:8443", "sharma.flowqr.site:80x", "1.2.3.4", "[::1]", "xn--sharma-abc.flowqr.site", "shärma.flowqr.site", "sharma.flowqr.site\x00", "sharma .flowqr.site",
                                  "sharma.flowqr.site/evil", "sharma@evil.com.flowqr.site", "sharma.flowqr.site, evil.com", "x" * 300 + ".flowqr.site", ".flowqr.site", "-.flowqr.site", "ab.flowqr.site"])
def test_hosts_that_never_resolve(host):
    assert rules.slug_from_host(host, BASE) is None


def test_host_resolution_depends_on_the_configured_base_only():
    assert rules.slug_from_host("sharma.sites.example", "sites.example") == "sharma" and rules.slug_from_host("sharma.flowqr.site", "sites.example") is None


# ---------------------------------------------------------------------------------------------------------------- links
@pytest.mark.parametrize("kind,url", [("maps", "https://maps.app.goo.gl/abc123"), ("maps", "https://www.google.com/maps/place/x"), ("review", "https://g.page/r/abc/review"), ("social", "https://www.instagram.com/sharma"),
                                      ("order", "https://www.zomato.com/kanpur/sharma"), ("social", "https://wa.me/919876543210")])
def test_allowed_links(kind, url):
    assert rules.clean_https_url(url, kind) == url


@pytest.mark.parametrize("kind,url", [("maps", "javascript:alert(1)"), ("maps", "data:text/html,<script>1</script>"), ("maps", "http://www.google.com/maps"), ("maps", "//www.google.com/maps"), ("maps", "https://evil.com/maps"),
                                      ("maps", "https://google.com.evil.com/x"), ("maps", "https://evilgoogle.com/x"), ("maps", "https://user:pw@www.google.com/maps"), ("social", "https://evil.com/instagram.com"),
                                      ("maps", "https://www.google.com/maps ok"), ("maps", "ftp://www.google.com"), ("order", "https://evil.example/order"), ("maps", "vbscript:x"),
                                      ("maps", "https:///www.google.com"), ("maps", "https://www.google.com/" + "a" * 600)])
def test_refused_links(kind, url):
    with pytest.raises(ValueError):
        rules.clean_https_url(url, kind)


def test_surrounding_whitespace_is_trimmed_not_trusted():
    assert rules.clean_https_url("  https://www.google.com/maps" + chr(10), "maps") == "https://www.google.com/maps" and rules.clean_https_url("   ", "maps") is None


def test_phone_links_are_built_from_digits_only():
    assert rules.tel_href("+91 98765 43210") == "tel:+919876543210" and rules.tel_href("98765 43210") == "tel:+919876543210"
    assert rules.whatsapp_href("98765 43210", "Hi there") == "https://wa.me/919876543210?text=Hi%20there"
    assert rules.tel_href("<script>") is None and rules.whatsapp_href("12") is None and rules.tel_href(None) is None


# ---------------------------------------------------------------------------------------------------------------- content validation
def test_unknown_keys_anywhere_are_refused():
    c = valid()
    c["evil"] = 1
    c["business"]["onclick"] = "x"
    c["sections"][0]["data"]["script"] = "x"
    c["sections"][0]["style"] = "x"
    _, errs = CT.validate_content(c, "clinic", set())
    paths = {e["path"] for e in errs}
    assert {"evil", "business.onclick", "sections[0].data.script", "sections[0].style"} <= paths


def test_text_is_kept_as_text_and_invisible_characters_are_removed():
    c = valid()
    c["business"]["tagline"] = "Open‮ now​!\x00\x07"
    c["sections"][0]["data"]["heading"] = "  Two   spaces\nand a newline  "
    clean, errs = CT.validate_content(c, "clinic", set())
    assert not errs and clean["business"]["tagline"] == "Open now!" and clean["sections"][0]["data"]["heading"] == "Two spaces and a newline"


@pytest.mark.parametrize("payload", XSS)
def test_markup_in_content_is_stored_as_plain_text(payload):
    c = valid()
    c["sections"][0]["data"]["subheading"] = payload
    clean, errs = CT.validate_content(c, "clinic", set())
    assert not errs and clean["sections"][0]["data"]["subheading"] == payload  # validation does not rewrite it; the renderer escapes it


def test_lengths_counts_and_types_are_enforced():
    c = valid()
    c["business"]["name"] = "x" * 121
    c["seo"]["title"] = "x" * 71
    c["seo"]["description"] = "x" * 161
    c["sections"][1]["data"]["items"] = [{"title": "t", "detail": "d"}] * 20
    c["business"]["email"] = "not-an-email"
    c["business"]["phone"] = "123"
    c["theme"]["accent"] = "hotpink"
    c["cta"]["primary"]["kind"] = "download"
    _, errs = CT.validate_content(c, "clinic", set())
    paths = {e["path"] for e in errs}
    assert {"business.name", "seo.title", "seo.description", "sections[1].data.items", "business.email", "business.phone", "theme.accent", "cta.primary.kind"} <= paths


def test_link_fields_use_the_allowlist():
    c = valid()
    c["business"]["maps_url"] = "https://evil.example/x"
    c["business"]["instagram"] = "javascript:alert(1)"
    c["business"]["review_url"] = "https://evil.example/review"
    c["business"]["order_url"] = "http://www.zomato.com/x"
    _, errs = CT.validate_content(c, "clinic", set())
    assert {"business.maps_url", "business.instagram", "business.review_url", "business.order_url"} <= {e["path"] for e in errs}


def test_images_must_belong_to_the_site():
    mine, other = ID(), ID()
    c = valid()
    c["sections"][0]["data"]["image"] = other
    c["business"]["logo"] = mine
    clean, errs = CT.validate_content(c, "clinic", {mine})
    assert [e["path"] for e in errs] == ["sections[0].data.image"] and clean["sections"][0]["data"]["image"] is None and clean["business"]["logo"] == mine
    c["sections"][0]["data"]["image"] = "not-a-uuid"
    assert CT.validate_content(c, "clinic", {mine})[1]


def test_sections_must_exist_in_the_template_and_be_unique_where_required():
    c = valid("clinic")
    c["sections"].append({"id": "x1", "type": "menu", "enabled": True, "data": {}})  # a restaurant section on a clinic site
    c["sections"].append({"id": "x2", "type": "hero", "enabled": True, "data": {}})  # a second hero
    c["sections"].append({"id": "s01", "type": "about", "enabled": True, "data": {}})  # a duplicate id
    c["sections"].append({"id": "Bad Id", "type": "about", "enabled": True, "data": {}})
    _, errs = CT.validate_content(c, "clinic", set())
    assert len(errs) >= 4
    c = valid("clinic")
    c["sections"] = c["sections"] * 3
    assert any(e["path"] == "sections" for e in CT.validate_content(c, "clinic", set())[1])


def test_opening_hours_format():
    c = valid()
    c["business"]["hours"][0].update({"open": "9am", "close": "6pm"})
    c["business"]["hours"][1]["day"] = "Monday"  # a duplicate day
    assert len(CT.validate_content(c, "clinic", set())[1]) >= 2
    c = valid()
    c["business"]["hours"] = c["business"]["hours"][:5]
    assert CT.validate_content(c, "clinic", set())[1]


# ---------------------------------------------------------------------------------------------------------------- the publish check
def test_a_new_draft_is_not_publishable_and_says_what_is_missing():
    b = CT.publish_blockers(valid("clinic"), "clinic", {})
    text = " ".join(x["message"] for x in b)
    assert "Conditions treated" in text and "Treatments" in text or "Services" in text
    assert any("Opening" in x["message"] or "hours" in x["message"] for x in CT.publish_blockers(valid("restaurant"), "restaurant", {}))


@pytest.mark.parametrize("key", list(C.TEMPLATES))
def test_a_fully_written_site_passes_for_every_template(key):
    c = filled(key)
    assert CT.publish_blockers(c, key, {}) == [], CT.publish_blockers(c, key, {})


def test_every_image_needs_alt_text_to_publish():
    img = ID()
    c = filled("clinic")
    c["sections"][0]["data"]["image"] = img
    assert any("alt text" in x["message"] for x in CT.publish_blockers(c, "clinic", {img: {"alt_text": ""}}))
    assert not any("alt text" in x["message"] for x in CT.publish_blockers(c, "clinic", {img: {"alt_text": "The reception"}}))
    assert any("missing" in x["message"] for x in CT.publish_blockers(c, "clinic", {}))


def test_a_clinic_cannot_publish_without_its_health_disclaimer_and_a_contact_detail():
    c = filled("clinic")
    c["sections"] = [s for s in c["sections"] if s["type"] != "disclaimer"]
    assert any("disclaimer" in x["message"] for x in CT.publish_blockers(c, "clinic", {}))
    c = filled("salon")
    c["business"].update({"phone": "", "whatsapp": "", "email": ""})
    assert any("contact" in x["message"] for x in CT.publish_blockers(c, "salon", {}))


# ---------------------------------------------------------------------------------------------------------------- templates
def test_the_six_templates_are_structurally_different():
    assert set(C.TEMPLATES) == {"clinic", "salon", "restaurant", "retail", "home_services", "professional"}
    layouts = {k: tuple(s for s, _ in t["default_sections"]) for k, t in C.TEMPLATES.items()}
    assert len(set(layouts.values())) == 6, "two templates share the same sections in the same order"
    assert len({t["hero"] for t in C.TEMPLATES.values()}) == 6, "two templates share a hero"
    for a in layouts:
        for b in layouts:
            if a < b:
                assert len(set(layouts[a]) ^ set(layouts[b])) >= 2, (a, b)  # not just a reordering
    # each template's signature sections
    assert {"credentials", "conditions", "process", "disclaimer"} <= set(layouts["clinic"]) and "menu" in layouts["restaurant"] and "price_menu" in layouts["salon"]
    assert {"products", "featured"} <= set(layouts["retail"]) and "areas" in layouts["home_services"] and "practice" in layouts["professional"]
    assert "menu" not in layouts["clinic"] and "disclaimer" not in layouts["salon"]


def test_each_template_renders_its_own_markup_and_layout_rules():
    pages = {k: build(filled(k), k)["index.html"].decode() for k in C.TEMPLATES}
    assert 'class="appt"' in pages["clinic"] and all('class="appt"' not in pages[k] for k in pages if k != "clinic")
    assert 'class="mcat"' in pages["restaurant"] and 'class="vm vm-veg"' in pages["restaurant"] and 'class="mcat"' not in pages["clinic"]
    assert 'class="menu2"' in pages["salon"] and 'class="info wrap"' in pages["retail"] and 'class="areas"' in pages["home_services"] and 'class="pr"' in pages["professional"]
    assert len({re.sub(r"\s+", " ", p) for p in pages.values()}) == 6
    h2s = {k: tuple(re.findall(r"<h2[^>]*>(.*?)</h2>", p)) for k, p in pages.items()}
    assert len(set(h2s.values())) == 6


@pytest.mark.parametrize("key", list(C.TEMPLATES))
def test_default_content_is_valid_for_every_template_and_uses_the_business_record(key):
    c = valid(key)
    assert c["business"]["name"] == "Sharma Physio" and c["business"]["phone"] == "+91 98765 43210" and c["sections"][0]["type"] == "hero" and c["sections"][0]["data"]["heading"] == "Sharma Physio"
    assert c["seo"]["title"] and len(c["seo"]["title"]) <= 70 and c["seo"]["description"] and len(c["seo"]["description"]) <= 160


@pytest.mark.parametrize("category,key", [("Physiotherapy clinic", "clinic"), ("Dental clinic", "clinic"), ("Salon or spa", "salon"), ("Restaurant or cafe", "restaurant"), ("Sweet shop or bakery", "restaurant"),
                                         ("Grocery or general store", "retail"), ("Clothing or footwear", "retail"), ("Electronics or mobile", "retail"), ("Plumber", "home_services"), ("Gym or fitness", "professional"),
                                         ("Lawyer", "professional"), (None, "professional"), ("Something unusual", "professional")])
def test_template_suggestion_from_the_business_category(category, key):
    assert C.suggest_template(category) == key


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


@pytest.mark.parametrize("name,hexv", list(C.ACCENTS.items()))
def test_every_accent_is_readable_with_a_white_label(name, hexv):
    assert 1.05 / (_lum(hexv) + 0.05) >= 4.5, name


# ---------------------------------------------------------------------------------------------------------------- rendering
@pytest.mark.parametrize("key", list(C.TEMPLATES))
def test_output_is_deterministic(key):
    c = filled(key)
    assert build(c, key) == build(c, key)


@pytest.mark.parametrize("key", list(C.TEMPLATES))
def test_pages_ship_no_javascript_no_inline_style_and_no_event_handlers(key):
    files = build(filled(key), key)
    for path, body in files.items():
        if not path.endswith(".html"):
            continue
        h = body.decode()
        executable = [s for s in re.findall(r"<script[^>]*>", h) if "application/ld+json" not in s]
        assert not executable, (path, executable)
        assert not re.search(r"\sstyle\s*=", h) and not re.search(r"<style", h), path  # the CSP forbids inline styles
        assert not re.search(r"\son[a-z]+\s*=", h, re.I), path
        assert "javascript:" not in h.lower() and "<iframe" not in h and "<object" not in h and "<embed" not in h and "<base" not in h, path


class _Tags(HTMLParser):
    """Everything an HTML parser would see in the page: tags and their attributes."""

    def __init__(self):
        super().__init__()
        self.tags, self.attrs, self.scripts = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += [(tag, k, v) for k, v in attrs]
        if tag == "script":
            self.scripts.append(dict(attrs).get("type"))


ALLOWED_TAGS = {"html", "head", "meta", "title", "link", "script", "body", "div", "a", "span", "header", "nav", "main", "footer", "section", "aside", "article", "h1", "h2", "h3", "p", "ul", "ol", "li", "img",
                "figure", "figcaption", "table", "caption", "tbody", "tr", "th", "td", "form", "label", "input", "textarea", "button", "details", "summary", "br", "hr", "strong", "small", "em", "dl", "dt", "dd"}


@pytest.mark.parametrize("payload", XSS)
@pytest.mark.parametrize("key", list(C.TEMPLATES))
def test_business_content_can_never_become_markup(key, payload):
    c = fill_strings(filled(key), payload)
    clean, _ = CT.validate_content(c, key, set())
    for path, body in build(clean, key).items():
        if not path.endswith(".html"):
            continue
        p = _Tags()
        p.feed(body.decode())
        assert set(p.tags) <= ALLOWED_TAGS, (path, set(p.tags) - ALLOWED_TAGS)  # no <svg>, <img src=x> from content, <iframe>, <object>...
        assert p.scripts in ([], ["application/ld+json"]), p.scripts
        bad = [(t, k, v) for t, k, v in p.attrs if k.startswith("on") or k == "style" or (k in ("href", "src", "action") and v and not re.match(r"^(#|/|tel:|mailto:|https://|data:image/webp;base64,)", v))]
        assert not bad, (path, bad)
        assert "javascript:" not in " ".join(v or "" for _, k, v in p.attrs if k in ("href", "src", "action")).lower()
    # the text is shown, as text
    assert "&lt;" in build(clean, key)["index.html"].decode() or "<" not in payload


def test_a_name_containing_a_script_end_tag_cannot_break_out_of_the_structured_data():
    c = filled("clinic")
    c["business"]["name"] = "</script><script>alert(1)</script>"
    html = build(c, "clinic")["index.html"].decode()
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert len(blocks) == 1 and json.loads(blocks[0])["name"] == "</script><script>alert(1)</script>"
    assert html.count("<script") == 1


def test_seo_metadata_and_structured_data():
    c = filled("restaurant")
    c["seo"].update({"title": "Sharma Restaurant | Kanpur", "description": "Family restaurant in Kanpur."})
    c["business"].update({"instagram": "https://www.instagram.com/sharma", "maps_url": "https://maps.app.goo.gl/abc"})
    files = build(c, "restaurant")
    h = files["index.html"].decode()
    assert "<title>Sharma Restaurant | Kanpur</title>" in h and '<meta name="description" content="Family restaurant in Kanpur.">' in h
    assert '<link rel="canonical" href="https://sharma.flowqr.site/">' in h and 'content="index,follow"' in h and 'lang="en-IN"' in h
    assert 'property="og:title"' in h and 'property="og:url" content="https://sharma.flowqr.site/"' in h and 'name="viewport"' in h
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S).group(1))
    assert ld["@type"] == "Restaurant" and ld["name"] == "Sharma Physio" and ld["url"] == "https://sharma.flowqr.site/" and ld["address"]["addressLocality"] == "Kanpur"
    assert ld["sameAs"] == ["https://www.instagram.com/sharma"] and ld["hasMap"] == "https://maps.app.goo.gl/abc" and len(ld["openingHoursSpecification"]) == 6
    assert "aggregateRating" not in ld and "review" not in ld  # nothing the business has not provided, and no invented ratings
    robots, sitemap = files["robots.txt"].decode(), files["sitemap.xml"].decode()
    assert "Sitemap: https://sharma.flowqr.site/sitemap.xml" in robots and "Disallow: /thanks/" in robots
    assert "<loc>https://sharma.flowqr.site/</loc>" in sitemap and "<loc>https://sharma.flowqr.site/privacy/</loc>" in sitemap and "/thanks/" not in sitemap
    for p in ("thanks/index.html", "problem/index.html"):
        assert 'content="noindex,nofollow"' in files[p].decode()


def test_drafts_and_previews_are_noindex_and_self_contained():
    c = filled("clinic")
    prev = build(c, "clinic", preview=True)
    assert list(prev) == ["index.html"]
    h = prev["index.html"].decode()
    assert 'content="noindex,nofollow"' in h and "<style>" in h and 'rel="canonical"' not in h and "Preview. This page is not published." in h
    assert 'action="#"' in h and 'type="submit"' not in h and 'rel="stylesheet"' not in h and "application/ld+json" not in h


def test_images_are_referenced_by_hashed_path_with_alt_and_sizes_and_only_used_ones_are_published():
    used, unused = ID(), ID()
    data = b"RIFF\x00\x00\x00\x00WEBPfakeimagebytes"
    assets = {used: R.Asset(used, "a" * 64, 800, 600, "The reception desk", data), unused: R.Asset(unused, "b" * 64, 10, 10, "Unused", b"zzz")}
    c = filled("clinic")
    c["sections"][0]["data"]["image"] = used
    files = build(c, "clinic", assets)
    h = files["index.html"].decode()
    assert '<img src="/assets/aaaaaaaaaaaaaaaa.webp" width="800" height="600" alt="The reception desk"' in h and 'fetchpriority="high"' in h
    assert "assets/aaaaaaaaaaaaaaaa.webp" in files and "assets/bbbbbbbbbbbbbbbb.webp" not in files and files["assets/aaaaaaaaaaaaaaaa.webp"] == data
    assert "data:image" not in h
    prev = build(c, "clinic", assets, preview=True)["index.html"].decode()
    assert "data:image/webp;base64," in prev and 'src="/assets/' not in prev


def test_accessibility_basics_on_every_template():
    for key in C.TEMPLATES:
        h = build(filled(key), key)["index.html"].decode()
        assert h.count("<h1") == 1 and "<main" in h and "<header" in h and "<footer" in h and 'class="skip"' in h and "<nav" in h
        assert re.findall(r"<img(?![^>]*\balt=)", h) == []
        assert 'aria-label' in h


def test_the_enquiry_form_has_consent_a_honeypot_and_posts_to_its_own_site():
    h = build(filled("clinic"), "clinic")["index.html"].decode()
    assert 'method="post" action="/_enquiry"' in h and 'name="consent" value="yes" required' in h and 'name="website"' in h and 'class="hp"' in h and "180 days" in h
    assert "/privacy/" in h
    c = filled("clinic")
    for s in c["sections"]:
        if s["type"] == "contact":
            s["data"]["show_enquiry"] = False
    assert "/_enquiry" not in build(c, "clinic")["index.html"].decode()


def test_the_privacy_page_states_what_is_collected_how_long_and_that_there_are_no_trackers():
    p = build(filled("clinic"), "clinic")["privacy/index.html"].decode()
    for needle in ("no cookies", "no tracking", "180 days", "Sharma Physio", "delete your enquiry"):
        assert needle in p.replace("\n", " "), needle


def test_the_stylesheet_has_a_content_hashed_name_and_no_external_urls():
    files = build(filled("clinic"), "clinic")
    css = [p for p in files if p.endswith(".css")]
    assert len(css) == 1 and re.match(r"style\.[0-9a-f]{10}\.css$", css[0])
    body = files[css[0]].decode()
    assert "@import" not in body and "url(" not in body and "http" not in body and "gradient" not in body
    assert f'href="/{css[0]}"' in files["index.html"].decode()


def test_every_site_has_a_plain_favicon_in_its_accent_colour_and_no_page_needs_a_missing_file():
    files = build(filled("clinic"), "clinic")
    fav = files["favicon.svg"].decode()
    assert C.ACCENTS["teal"] in fav and "<script" not in fav and "<text" not in fav and 'href="/favicon.svg"' in files["index.html"].decode()
    for path in ("index.html", "privacy/index.html", "thanks/index.html", "problem/index.html"):
        for ref in re.findall(r'(?:href|src)="(/[^"#]*)"', files[path].decode()):
            if ref.endswith("/"):
                assert ref.lstrip("/") + "index.html" in files or ref == "/", (path, ref)
            else:
                assert ref.lstrip("/") in files, (path, ref)  # every local file a page refers to is in the published set


def test_the_manifest_lists_every_file_with_its_checksum():
    files = build(filled("clinic"), "clinic")
    m = json.loads(files["_manifest.json"])
    assert m["template"] == "clinic" and set(m["files"]) == {p for p in files if p != "_manifest.json"}


# ---------------------------------------------------------------------------------------------------------------- the HTML builder itself
def test_the_builder_escapes_by_construction_and_refuses_dangerous_names():
    assert str(el("p", {"class": 'a"b'}, '<b>&</b>')) == '<p class="a&quot;b">&lt;b&gt;&amp;&lt;/b&gt;</p>'
    for bad in (lambda: el("script", None, "x"), lambda: el("style", None, "x"), lambda: el("iframe"), lambda: el("a", {"onclick": "x"}), lambda: el("a", {"style": "x"}),
                lambda: el("a", {"href": "javascript:alert(1)"}), lambda: el("a", {"href": "data:text/html;base64,AAAA"}), lambda: el("img", {"src": "http://evil.example/x.png"}),
                lambda: el("a", {"href": "https://x.example/a b"}), lambda: el("form", {"action": "//evil.example"}), lambda: el("a", {"href": "//evil.example/x"}), lambda: el("a", {"href": "/\\evil.example"}), lambda: el("a", {"HREF": "x", "bad attr": "y"})):
        with pytest.raises(ValueError):
            bad()
    assert "href" in str(el("a", {"href": "https://www.google.com/maps"}, "x")) and 'href="tel:+919876543210"' in str(el("a", {"href": "tel:+919876543210"}))
    assert "<script" in str(json_ld({"a": "</script>"})) and str(json_ld({"a": "</script>"})).count("<script") == 1
