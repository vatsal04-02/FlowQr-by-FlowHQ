"""Turns validated website content into static files.

`build_site()` is a pure function: the same content always produces the same bytes (no timestamps, sorted keys, content-hashed file names), so a publish can be compared, retried and rolled
back safely. It reads only the validated content (never a draft that has not passed validation), escapes every value through htmlkit, and ships NO JavaScript: the pages work from plain
HTML and CSS, which is what lets the hosting Worker send a Content-Security-Policy of `script-src 'none'` (see hosting.CSP).

Pages: / (the website), /privacy/, /thanks/ and /problem/ (where the enquiry form lands), robots.txt, sitemap.xml, the stylesheet and the referenced images."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import quote

from app.services.sites import catalog as C
from app.services.sites.css import stylesheet
from app.services.sites.htmlkit import Raw, el, json_ld, raw_style
from app.services.sites.rules import digits, tel_href, whatsapp_href

POWERED_BY = "https://www.flowqr.site"
NAV_LABEL = {"reviews": "Reviews", "about": "About", "services": "Services", "price_menu": "Prices", "menu": "Menu", "credentials": "Credentials", "conditions": "Conditions", "process": "Process", "faqs": "Questions",
             "gallery": "Gallery", "team": "Team", "offers": "Offers", "products": "Products", "featured": "Featured", "areas": "Areas", "trust": "Why us", "practice": "Practice", "hours": "Hours",
             "location": "Location", "contact": "Contact"}
SCHEMA_TYPE = {"clinic": "MedicalBusiness", "salon": "BeautySalon", "restaurant": "Restaurant", "retail": "Store", "home_services": "LocalBusiness", "professional": "ProfessionalService"}
ABBR = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}


@dataclass
class Asset:
    id: str
    sha256: str
    width: int
    height: int
    alt: str
    data: bytes | None = None

    @property
    def path(self) -> str:
        return f"/assets/{self.sha256[:16]}.webp"

    @property
    def key(self) -> str:
        return f"assets/{self.sha256[:16]}.webp"


class Ctx:
    def __init__(self, content: dict, template_key: str, host: str, assets: dict[str, Asset], preview: bool, retention_days: int, base: str = "", origin: str | None = None, reviews: dict | None = None):
        self.c, self.t, self.host, self.assets, self.preview, self.retention = content, template_key, host, assets, preview, retention_days
        self.base, self.origin, self.reviews = base.rstrip("/"), "https://" + (origin or host).split("://")[-1].rstrip("/"), reviews  # `base` is the path the site is served under ("" = its own host)
        self.b = content["business"]
        self.secs = [s for s in content["sections"] if s["enabled"]]
        self.has_enquiry = any(s["type"] == "contact" and s["data"].get("show_enquiry") for s in self.secs)

    # ---- links built from validated values only
    def href(self, path: str) -> str:
        if self.preview:
            return "#"
        return self.base + path if path.startswith("/") else path

    def maps_href(self) -> str | None:
        if self.b.get("maps_url"):
            return self.b["maps_url"]
        q = ", ".join(x for x in (self.b.get("name"), self.b.get("address"), self.b.get("city")) if x)
        return f"https://www.google.com/maps/search/?api=1&query={quote(q)}" if self.b.get("address") or self.b.get("city") else None

    def cta_href(self, cta: dict | None) -> tuple[str, str] | None:
        if not cta or not cta.get("label"):
            return None
        k, b = cta["kind"], self.b
        href = None
        if k == "call":
            href = tel_href(b.get("phone") or b.get("whatsapp"))
        elif k == "whatsapp":
            href = whatsapp_href(b.get("whatsapp") or b.get("phone"), b.get("whatsapp_message"))
        elif k == "enquiry":
            href = "#contact" if self.has_enquiry else (tel_href(b.get("phone")) or (f"mailto:{b['email']}" if b.get("email") else None))
        elif k == "directions":
            href = self.maps_href()
        elif k == "order":
            href = b.get("order_url") or None
        return (href, cta["label"]) if href else None

    def img(self, aid: str | None, cls: str | None = None, eager: bool = False) -> Raw | None:
        a = self.assets.get(aid or "")
        if not a:
            return None
        src = ("data:image/webp;base64," + base64.b64encode(a.data or b"").decode()) if self.preview else self.base + a.path
        return el("img", {"src": src, "width": a.width, "height": a.height, "alt": a.alt, "class": cls, "loading": None if eager else "lazy", "decoding": "async", "fetchpriority": "high" if eager else None})


# ------------------------------------------------------------------------------------------------------------------ small pieces
def hours_summary(hours: list[dict]) -> list[tuple[str, str]]:
    """Consecutive days with the same hours grouped: [('Mon–Sat', '10:00 – 21:00'), ('Sun', 'Closed')]. Days with nothing set are left out."""
    rows = []
    for h in hours:
        label = "Closed" if h["closed"] else (f"{h['open']} – {h['close']}" if h["open"] and h["close"] else None)
        if label:
            rows.append((h["day"], label))
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1][1] == rows[i][1] and C.DAYS.index(rows[j + 1][0]) == C.DAYS.index(rows[j][0]) + 1:
            j += 1
        out.append((ABBR[rows[i][0]] if i == j else f"{ABBR[rows[i][0]]}–{ABBR[rows[j][0]]}", rows[i][1]))
        i = j + 1
    return out


def hours_table(hours: list[dict], cls: str = "hrs") -> Raw | None:
    rows = [(h["day"], "Closed" if h["closed"] else f"{h['open']} – {h['close']}") for h in hours if h["closed"] or (h["open"] and h["close"])]
    if not rows:
        return None
    return el("table", {"class": cls}, el("caption", {"class": "hp"}, "Opening hours"), el("tbody", None, [el("tr", None, el("th", {"scope": "row"}, d), el("td", None, v)) for d, v in rows]))


def paragraphs(s: str) -> list[Raw]:
    return [el("p", None, p.strip()) for p in (s or "").split("\n\n") if p.strip()]


def btn(ctx: Ctx, cta: dict | None, alt: bool = False) -> Raw | None:
    r = ctx.cta_href(cta)
    if not r:
        return None
    href, label = r
    return el("a", {"class": "btn" + (" alt" if alt else ""), "href": ctx.href(href)}, label)


def head(ctx: Ctx, sid: str, heading: str, intro: str | None = None) -> Raw:
    return el("div", {"class": "sh"}, el("h2", {"id": f"{sid}-h"}, heading), el("p", None, intro) if intro else None)


def section(sid: str, body, cls: str = "s") -> Raw:
    return el("section", {"class": cls, "id": sid, "aria-labelledby": f"{sid}-h"}, el("div", {"class": "wrap"}, body))


def card_list(ctx: Ctx, items: list[dict], title="title", detail="detail", price=None, image=None, cls="grid") -> Raw:
    lis = []
    for it in items:
        lis.append(el("li", {"class": "card"}, ctx.img(it.get(image)) if image else None, el("h3", None, it.get(title)), el("p", None, it.get(detail)) if it.get(detail) else None,
                      el("p", {"class": "price"}, it.get(price)) if price and it.get(price) else None))
    return el("ul", {"class": cls}, lis)


# ------------------------------------------------------------------------------------------------------------------ heroes (one per template)
def hero(ctx: Ctx, sec: dict) -> Raw:
    d, b, t = sec["data"], ctx.b, ctx.t
    eyebrow = el("p", {"class": "eyebrow"}, d["eyebrow"]) if d.get("eyebrow") else None
    h1 = el("h1", None, d["heading"])
    lead = el("p", {"class": "lead"}, d["subheading"]) if d.get("subheading") else None
    btns = el("div", {"class": "btns"}, btn(ctx, ctx.c["cta"]["primary"]), btn(ctx, ctx.c["cta"]["secondary"], alt=True))
    image = ctx.img(d.get("image"), "hi", eager=True)
    text_block = [eyebrow, h1, lead, btns]
    if t == "clinic":
        mini = hours_table(b["hours"])
        side = el("aside", {"class": "appt", "aria-label": "Appointments"}, el("h2", None, "Appointments"),
                  el("p", None, el("a", {"href": ctx.href(tel_href(b.get("phone") or b.get("whatsapp")) or "#")}, b.get("phone") or b.get("whatsapp"))) if (b.get("phone") or b.get("whatsapp")) else None,
                  mini, btn(ctx, ctx.c["cta"]["primary"]))
        return el("header", {"class": "hero"}, el("div", {"class": "wrap"}, el("div", None, text_block, image), side))
    if t == "salon":
        return el("header", {"class": "hero"}, image, el("div", {"class": "wrap"}, text_block))
    if t in ("restaurant", "home_services"):
        chips = None
        if t == "home_services":
            names = [i.get("title") for s in ctx.secs if s["type"] == "trust" for i in s["data"].get("items", [])][:4]
            chips = el("ul", {"class": "chips"}, [el("li", None, n) for n in names]) if names else None
        return el("header", {"class": "hero"}, el("div", {"class": "wrap"}, el("div", None, text_block, chips), image))
    if t == "retail":
        sm = hours_summary(b["hours"])
        info = el("div", {"class": "info wrap"},
                  el("div", None, el("strong", None, "Address"), b.get("address") or b.get("city") or "") if (b.get("address") or b.get("city")) else None,
                  el("div", None, el("strong", None, "Hours"), "; ".join(f"{a} {v}" for a, v in sm)) if sm else None,
                  el("div", None, el("strong", None, "Phone"), el("a", {"href": ctx.href(tel_href(b["phone"]) or "#")}, b["phone"])) if b.get("phone") else None)
        return el("header", {"class": "hero"}, el("div", {"class": "wrap"}, el("div", None, text_block), image), info)
    # professional
    return el("header", {"class": "hero"}, el("div", {"class": "wrap"}, eyebrow, h1, lead, el("hr", {"class": "rule"}), btns, image))


# ------------------------------------------------------------------------------------------------------------------ sections
def contact_block(ctx: Ctx, sec: dict) -> Raw:
    b, d, sid = ctx.b, sec["data"], sec["id"]
    dl = []
    if b.get("phone"):
        dl.append(el("p", None, "Phone: ", el("a", {"href": ctx.href(tel_href(b["phone"]) or "#")}, b["phone"])))
    wa = whatsapp_href(b.get("whatsapp") or b.get("phone"), b.get("whatsapp_message"))
    if wa and (b.get("whatsapp") or b.get("phone")):
        dl.append(el("p", None, "WhatsApp: ", el("a", {"href": ctx.href(wa), "rel": "noopener noreferrer"}, b.get("whatsapp") or b.get("phone"))))
    if b.get("email"):
        dl.append(el("p", None, "Email: ", el("a", {"href": ctx.href("mailto:" + b["email"])}, b["email"])))
    if b.get("address"):
        dl.append(el("p", None, b["address"]))
    left = [head(ctx, sid, d["heading"], d.get("intro")), dl]
    form = None
    if d.get("show_enquiry"):
        form = el("form", {"class": "enq", "method": "post", "action": ctx.href("/_enquiry"), "id": "enquiry"},
                  el("label", None, "Your name", el("input", {"name": "name", "required": True, "maxlength": 120, "autocomplete": "name"})),
                  el("label", None, "Phone", el("input", {"name": "phone", "inputmode": "tel", "maxlength": 32, "autocomplete": "tel"})),
                  el("label", None, "Email", el("input", {"type": "email", "name": "email", "maxlength": 254, "autocomplete": "email"})),
                  el("label", None, "Message", el("textarea", {"name": "message", "required": True, "rows": 4, "maxlength": 1500})),
                  el("label", {"class": "hp", "aria-hidden": "true"}, "Leave this empty", el("input", {"name": "website", "tabindex": -1, "autocomplete": "off"})),
                  el("label", {"class": "chk"}, el("input", {"type": "checkbox", "name": "consent", "value": "yes", "required": True}),
                     el("span", None, f"I agree that {b['name']} may contact me about this enquiry and keep my details for {ctx.retention} days. ", el("a", {"href": ctx.href("/privacy/")}, "Privacy notice"), ".")),
                  el("label", {"class": "chk"}, el("input", {"type": "checkbox", "name": "whatsapp_ok", "value": "yes"}),
                     el("span", None, f"I would also like updates about this enquiry on WhatsApp from {b['name']}. I can reply STOP at any time.")) if d.get("whatsapp_optin") else None,
                  el("button", {"class": "btn", "type": "button" if ctx.preview else "submit"}, "Send enquiry"),
                  el("p", {"class": "small"}, "Please give a phone number or an email so the business can reply."))
    return section(sid, el("div", {"class": "cols"}, el("div", None, left), form), "s")


def stars(n: float) -> Raw:
    full = max(0, min(5, int(round(n))))
    return el("span", {"class": "stars", "role": "img", "aria-label": f"{n} out of 5 stars" if n != int(n) else f"{int(n)} out of 5 stars"}, "\u2605" * full + "\u2606" * (5 - full))


def reviews_block(ctx: Ctx, sec: dict) -> Raw | None:
    """Google reviews, read when the page is shown (never copied into the website): every star level, newest first. Nothing is shown when there are none."""
    rv, d, sid = ctx.reviews, sec["data"], sec["id"]
    if not rv or not rv.get("total"):
        return None
    summary = el("p", {"class": "rsum"}, el("strong", None, f"{rv['average']:.1f}"), stars(rv["average"]), el("span", None, f"{rv['total']} Google review{'s' if rv['total'] != 1 else ''}"))
    cards = [el("li", {"class": "rev"}, stars(i["rating"]), el("p", None, i["text"]) if i.get("text") else None, el("p", {"class": "who"}, i["name"], el("span", None, f" \u00b7 {i['date']}"))) for i in rv["items"]]
    link = ctx.b.get("maps_url") or ctx.maps_href()
    return section(sid, [head(ctx, sid, d["heading"]), summary, el("ul", {"class": "revs"}, cards), el("p", {"class": "small"}, "Reviews from Google, newest first. " + (d.get("note") or "")),
                         el("div", {"class": "btns"}, el("a", {"class": "btn alt", "href": ctx.href(link), "rel": "noopener noreferrer"}, "See all reviews on Google")) if link else None], "s tint")


def render_section(ctx: Ctx, sec: dict) -> Raw | None:
    typ, d, sid = sec["type"], sec["data"], sec["id"]
    if typ == "hero":
        return None
    if typ == "contact":
        return contact_block(ctx, sec)
    if typ == "reviews":
        return reviews_block(ctx, sec)
    H = head(ctx, sid, d.get("heading", ""), d.get("intro"))
    if typ == "about":
        return section(sid, el("div", {"class": "cols"}, el("div", None, head(ctx, sid, d["heading"]), paragraphs(d["body"]),
                                                              el("ul", {"class": "hl"}, [el("li", None, h) for h in d["highlights"]]) if d["highlights"] else None),
                                el("div", None, ctx.img(d.get("image")))))
    if typ == "services":
        return section(sid, [H, card_list(ctx, d["items"], "title", "description", "price", "image", "grid svc")])
    if typ == "price_menu":
        groups = [el("div", {"class": "grp"}, el("h3", None, g["title"]), el("ul", {"class": "rows"}, [el("li", None, el("span", None, i["name"], el("span", {"class": "note"}, i["note"]) if i["note"] else None),
                  el("span", {"class": "price"}, i["price"])) for i in g["items"]])) for g in d["groups"] if g["items"]]
        return section(sid, [H, el("div", {"class": "menu2"}, groups)])
    if typ == "menu":
        cats = []
        for c in d["categories"]:
            if not c["items"]:
                continue
            rows = []
            for i in c["items"]:
                mark = el("span", {"class": f"vm vm-{i['veg']}", "role": "img", "aria-label": {"veg": "Vegetarian", "nonveg": "Non-vegetarian", "egg": "Contains egg"}[i["veg"]]}) if i["veg"] else None
                rows.append(el("li", None, el("span", None, mark, el("strong", None, i["name"]), el("span", {"class": "note"}, i["description"]) if i["description"] else None), el("span", {"class": "price"}, i["price"])))
            cats.append(el("div", {"class": "mcat"}, el("h3", None, c["title"]), el("ul", {"class": "rows"}, rows)))
        legend = el("p", {"class": "small"}, "Green: vegetarian. Red: non-vegetarian. Amber: contains egg.")
        return section(sid, [H, cats, legend])
    if typ == "credentials":
        return section(sid, [H, el("ul", {"class": "rows"}, [el("li", None, el("span", None, el("strong", None, i["title"]), el("span", {"class": "note"}, i["detail"]) if i["detail"] else None)) for i in d["items"]])])
    if typ == "conditions":
        return section(sid, [H, el("ul", {"class": "chips"}, [el("li", None, i) for i in d["items"]])])
    if typ == "process":
        return section(sid, [H, el("ol", {"class": "steps"}, [el("li", None, el("h3", None, s["title"]), el("p", None, s["detail"]) if s["detail"] else None) for s in d["steps"]])])
    if typ == "faqs":
        return section(sid, [H, [el("details", {"class": "faq"}, el("summary", None, q["question"]), el("p", None, q["answer"])) for q in d["items"]]])
    if typ == "gallery":
        figs = [el("figure", None, ctx.img(i["asset"]), el("figcaption", None, i["caption"]) if i["caption"] else None) for i in d["images"] if ctx.assets.get(i["asset"] or "")]
        return section(sid, [H, el("div", {"class": "gal"}, figs)])
    if typ == "team":
        return section(sid, [H, el("ul", {"class": "team"}, [el("li", None, ctx.img(m["image"]), el("h3", None, m["name"]), el("span", {"class": "role"}, m["role"]) if m["role"] else None,
                                                             el("p", None, m["bio"]) if m["bio"] else None) for m in d["members"]])])
    if typ == "offers":
        return section(sid, [H, el("ul", {"class": "grid"}, [el("li", {"class": "card"}, el("h3", None, o["title"]), el("p", None, o["detail"]) if o["detail"] else None,
                                                             el("p", {"class": "small"}, "Valid until " + o["valid_until"]) if o["valid_until"] else None) for o in d["items"]])])
    if typ == "products":
        return section(sid, [H, card_list(ctx, d["categories"], "title", "detail", None, "image")])
    if typ == "featured":
        return section(sid, [H, card_list(ctx, d["items"], "name", "detail", "price", "image")])
    if typ == "areas":
        return section(sid, [H, el("ul", {"class": "areas"}, [el("li", None, a) for a in d["areas"]])])
    if typ == "trust":
        return section(sid, [H, card_list(ctx, d["items"], "title", "detail")])
    if typ == "practice":
        return section(sid, [H, el("ul", {"class": "pr"}, [el("li", None, el("h3", None, i["title"]), el("p", None, i["detail"]) if i["detail"] else None) for i in d["items"]])])
    if typ == "hours":
        tbl = hours_table(ctx.b["hours"])
        return section(sid, [head(ctx, sid, d["heading"]), tbl, el("p", {"class": "small"}, d["note"]) if d.get("note") else None]) if tbl else None
    if typ == "location":
        m = ctx.maps_href()
        return section(sid, [head(ctx, sid, d["heading"]), el("p", None, ctx.b.get("address") or ctx.b.get("city") or ""), el("p", {"class": "small"}, d["note"]) if d.get("note") else None,
                             el("div", {"class": "btns"}, el("a", {"class": "btn", "href": ctx.href(m), "rel": "noopener noreferrer"}, "Get directions")) if m else None])
    if typ == "disclaimer":
        return section(sid, [head(ctx, sid, d["heading"]), el("p", {"class": "dis"}, d["text"])])
    if typ == "cta_band":
        return el("section", {"class": "band", "id": sid, "aria-labelledby": f"{sid}-h"}, el("div", {"class": "wrap"}, el("h2", {"id": f"{sid}-h"}, d["heading"]), el("p", None, d["text"]) if d.get("text") else None,
                  el("div", {"class": "btns"}, btn(ctx, ctx.c["cta"]["primary"]))))
    return None


# ------------------------------------------------------------------------------------------------------------------ page shell
def schema_org(ctx: Ctx) -> dict:
    b, c = ctx.b, ctx.c
    o: dict = {"@context": "https://schema.org", "@type": SCHEMA_TYPE[ctx.t], "name": b["name"], "url": f"{ctx.origin}{ctx.base}/"}
    if b.get("phone"):
        o["telephone"] = b["phone"]
    if b.get("email"):
        o["email"] = b["email"]
    if b.get("address") or b.get("city"):
        o["address"] = {"@type": "PostalAddress", **({"streetAddress": b["address"]} if b.get("address") else {}), **({"addressLocality": b["city"]} if b.get("city") else {}), "addressCountry": "IN"}
    img = ctx.assets.get(c["seo"].get("og_image") or "") or ctx.assets.get(b.get("logo") or "")
    if img:
        o["image"] = f"{ctx.origin}{ctx.base}{img.path}"
    spec = [{"@type": "OpeningHoursSpecification", "dayOfWeek": h["day"], "opens": h["open"], "closes": h["close"]} for h in b["hours"] if not h["closed"] and h["open"] and h["close"]]
    if spec:
        o["openingHoursSpecification"] = spec
    same = [u for u in (b.get("instagram"), b.get("facebook"), b.get("youtube")) if u]
    if same:
        o["sameAs"] = same
    if b.get("maps_url"):
        o["hasMap"] = b["maps_url"]
    return o


def page(ctx: Ctx, *, title: str, description: str, path: str, body, index: bool = True, ld: bool = False, css_href: str = "", inline_css: str = "") -> str:
    accent = C.ACCENTS[ctx.c["theme"]["accent"]]
    url = f"{ctx.origin}{ctx.base}{path}"
    robots = "index,follow" if (index and not ctx.preview) else "noindex,nofollow"
    og_img = ctx.assets.get(ctx.c["seo"].get("og_image") or "") or ctx.assets.get(ctx.b.get("logo") or "")
    metas = [el("meta", {"charset": "utf-8"}), el("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}), el("title", None, title),
             el("meta", {"name": "description", "content": description}), el("meta", {"name": "robots", "content": robots}), el("meta", {"name": "theme-color", "content": accent})]
    if not ctx.preview:
        metas += [el("link", {"rel": "canonical", "href": url}), el("meta", {"property": "og:type", "content": "website"}), el("meta", {"property": "og:title", "content": title}),
                  el("meta", {"property": "og:description", "content": description}), el("meta", {"property": "og:url", "content": url}), el("meta", {"property": "og:locale", "content": "en_IN"}),
                  el("meta", {"property": "og:site_name", "content": ctx.b["name"]}),
                  el("meta", {"property": "og:image", "content": f"{ctx.origin}{ctx.base}{og_img.path}"}) if og_img else None,
                  el("meta", {"name": "twitter:card", "content": "summary_large_image" if og_img else "summary"})]
    metas.append(raw_style(inline_css) if ctx.preview else el("link", {"rel": "stylesheet", "href": css_href}))
    if not ctx.preview:
        metas.append(el("link", {"rel": "icon", "type": "image/svg+xml", "href": ctx.base + "/favicon.svg"}))
    if ld and not ctx.preview:
        metas.append(json_ld(schema_org(ctx)))
    banner = el("div", {"class": "pv", "role": "note"}, "Preview. This page is not published.") if ctx.preview else None
    doc = el("html", {"lang": "en-IN", "class": f"a-{ctx.c['theme']['accent']}"}, el("head", None, metas), el("body", {"class": f"t-{ctx.t}"}, banner, body))
    return "<!doctype html>\n" + str(doc) + "\n"


def shell(ctx: Ctx, main: list) -> Raw:
    b = ctx.b
    nav = [el("a", {"href": f"#{s['id']}"}, NAV_LABEL[s["type"]]) for s in ctx.secs if s["type"] in NAV_LABEL]
    logo = ctx.img(b.get("logo"), None, eager=True)
    call = btn(ctx, ctx.c["cta"]["primary"])
    header = el("header", {"class": "top"}, el("div", {"class": "wrap"}, el("a", {"class": "brand", "href": "#top"}, logo, el("span", None, b["name"])), el("nav", {"class": "nav", "aria-label": "Sections"}, nav), call))
    sm = hours_summary(b["hours"])
    social = [el("li", None, el("a", {"href": ctx.href(u), "rel": "noopener noreferrer"}, label)) for label, u in (("Instagram", b.get("instagram")), ("Facebook", b.get("facebook")), ("YouTube", b.get("youtube"))) if u]
    footer = el("footer", {"class": "foot"}, el("div", {"class": "wrap"},
                el("div", None, el("strong", None, b["name"]), el("br"), b.get("address") or b.get("city") or ""),
                el("ul", None, el("li", None, el("a", {"href": ctx.href(tel_href(b["phone"]) or "#")}, b["phone"])) if b.get("phone") else None,
                   el("li", None, el("a", {"href": ctx.href("mailto:" + b["email"])}, b["email"])) if b.get("email") else None,
                   [el("li", None, f"{a}: {v}") for a, v in sm]),
                el("ul", None, el("li", None, el("a", {"href": ctx.href(b["review_url"]), "rel": "noopener noreferrer"}, "Review us on Google")) if b.get("review_url") else None, social,
                   el("li", None, el("a", {"href": ctx.href("/privacy/")}, "Privacy notice")),
                   el("li", None, "Website by ", el("a", {"href": POWERED_BY, "rel": "noopener noreferrer"}, "FlowQR")))))
    p, s = ctx.cta_href(ctx.c["cta"]["primary"]), ctx.cta_href(ctx.c["cta"]["secondary"])
    sticky = el("div", {"class": "sticky"}, [el("a", {"class": "btn" + (" alt" if i else ""), "href": ctx.href(x[0])}, x[1]) for i, x in enumerate(v for v in (p, s) if v)]) if (p or s) else None
    return el("div", {"id": "top"}, el("a", {"class": "skip", "href": "#main"}, "Skip to content"), header, el("main", {"id": "main"}, main), footer, sticky)


def privacy_body(ctx: Ctx) -> Raw:
    b = ctx.b
    contact = " or ".join(x for x in (b.get("phone"), b.get("email")) if x) or "the business"
    items = [("Who runs this website", f"{b['name']}. The website is hosted and maintained for the business by FlowQR (FlowHQ)."),
             ("What this website collects", "Nothing, unless you send an enquiry. There are no cookies, no tracking, no analytics and no advertising on this website."),
             ("The enquiry form", "If you use it, we keep the name, phone number and email you enter and your message, the time you agreed to this notice, and a one-way code made from your internet address that is used only to stop abuse."),
             ("Why", f"So that {b['name']} can reply to you. Your details are shared only with the business and with FlowQR as its website provider. They are not sold or used for anything else."),
             ("How long", f"Enquiries are deleted automatically after {ctx.retention} days."),
             ("Your rights", f"You can ask to see, correct or delete your enquiry at any time by contacting {contact}.")]
    return el("div", {"id": "top"}, el("a", {"class": "skip", "href": "#main"}, "Skip to content"),
              el("header", {"class": "top"}, el("div", {"class": "wrap"}, el("a", {"class": "brand", "href": ctx.href("/")}, b["name"]))),
              el("main", {"id": "main"}, el("section", {"class": "s"}, el("div", {"class": "wrap"}, el("h1", None, "Privacy notice"), [[el("h2", None, h), el("p", None, t)] for h, t in items],
                                              el("p", None, el("a", {"href": ctx.href("/")}, "Back to the website"))))))


def message_body(ctx: Ctx, heading: str, text_: str) -> Raw:
    return el("div", {"id": "top"}, el("main", {"id": "main"}, el("section", {"class": "s"}, el("div", {"class": "wrap"}, el("h1", None, heading), el("p", {"class": "lead"}, text_),
                                                                      el("div", {"class": "btns"}, el("a", {"class": "btn", "href": ctx.href("/")}, "Back to the website"))))))


# ------------------------------------------------------------------------------------------------------------------ the build
def build_site(content: dict, template_key: str, *, host: str, assets: dict[str, Asset], retention_days: int = 180, preview: bool = False, base: str = "", origin: str | None = None,
               reviews: dict | None = None) -> dict[str, bytes]:
    """Static files for one site: {path: bytes}. `content` must already have passed validate_content. In preview mode the result is a single self-contained, noindex page."""
    ctx = Ctx(content, template_key, host, assets, preview, retention_days, base, origin, reviews)
    css = stylesheet(template_key)
    css_name = f"style.{hashlib.sha256(css.encode()).hexdigest()[:10]}.css"
    b, seo = ctx.b, content["seo"]
    hero_sec = next((s for s in ctx.secs if s["type"] == "hero"), None)
    main = [hero(ctx, hero_sec) if hero_sec else None] + [render_section(ctx, s) for s in ctx.secs if s["type"] != "hero"]
    title, desc = seo["title"] or b["name"], seo["description"] or b["name"]
    index = page(ctx, title=title, description=desc, path="/", body=shell(ctx, main), ld=True, css_href=f"{ctx.base}/{css_name}", inline_css=css)
    if preview:
        return {"index.html": index.encode()}
    files: dict[str, str | bytes] = {"index.html": index, f"{css_name}": css}
    files["privacy/index.html"] = page(ctx, title=f"Privacy notice | {b['name']}", description=f"How {b['name']} handles enquiries sent through this website.", path="/privacy/", body=privacy_body(ctx), css_href=f"{ctx.base}/{css_name}")
    files["thanks/index.html"] = page(ctx, title=f"Thank you | {b['name']}", description="Your enquiry was sent.", path="/thanks/", index=False, css_href=f"{ctx.base}/{css_name}",
                                      body=message_body(ctx, "Thank you", f"Your enquiry was sent to {b['name']}. They will contact you using the details you gave."))
    files["problem/index.html"] = page(ctx, title=f"Enquiry not sent | {b['name']}", description="Your enquiry could not be sent.", path="/problem/", index=False, css_href=f"{ctx.base}/{css_name}",
                                       body=message_body(ctx, "We could not send your enquiry", "Please check that you ticked the box, gave a phone number or email, and try again, or call the business."))
    files["favicon.svg"] = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="{C.ACCENTS[content["theme"]["accent"]]}"/></svg>'  # a plain square in the accent colour: no text, nothing from the business
    files["robots.txt"] = f"User-agent: *\nAllow: /\nDisallow: /thanks/\nDisallow: /problem/\nSitemap: {ctx.origin}{ctx.base}/sitemap.xml\n"
    files["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                            f"<url><loc>{ctx.origin}{ctx.base}/</loc></url>\n<url><loc>{ctx.origin}{ctx.base}/privacy/</loc></url>\n</urlset>\n")
    for aid in sorted(_used_assets(content), key=lambda x: assets[x].sha256 if x in assets else x):
        a = assets.get(aid)
        if a and a.data is not None:
            files[a.key] = a.data
    out = {k: (v.encode() if isinstance(v, str) else v) for k, v in files.items()}
    out["_manifest.json"] = json.dumps({"template": template_key, "template_version": C.TEMPLATE_VERSION, "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(out.items())}},
                                       sort_keys=True, indent=1).encode()
    return out


def _used_assets(content: dict) -> set[str]:
    from app.services.sites.content import referenced_assets

    return referenced_assets({"business": content["business"], "seo": content["seo"], "sections": [s for s in content["sections"] if s["enabled"]]})
