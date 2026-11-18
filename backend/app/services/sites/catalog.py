"""The website catalogue: section types (their fields, limits and labels), the six templates, the accent palettes, and the starting content built from a business record.

The section specs are the single source of truth: the validator (content.py) enforces them, the admin editor draws its forms from them (GET /admin/sites/templates), and the renderer reads
only fields that exist here. A template is code plus a content schema, not a colour theme: each one has its own set of sections in its own order, its own hero, and its own layout in render.py.
Nothing here is HTML: all business content is plain text that the renderer escapes."""
from __future__ import annotations

from typing import Any

TEMPLATE_VERSION = 1
MAX_SECTIONS = 20

# Accent colours: the only theme choice, a whitelist. Each is at least 4.5:1 against white (tests/test_sites_render.py checks it), so a white button label is always readable.
ACCENTS = {"ink": "#111111", "blue": "#1D4ED8", "navy": "#1E3A8A", "teal": "#0F766E", "green": "#166534", "red": "#B91C1C", "orange": "#B45309", "purple": "#6D28D9"}


def _f(key: str, label: str, kind: str = "text", **kw: Any) -> dict:
    return {"key": key, "label": label, "kind": kind, **kw}


def text(key, label, max=100, required=False, hint=None):
    return _f(key, label, "text", max=max, required=required, hint=hint)


def area(key, label, max=500, required=False, hint=None):
    return _f(key, label, "textarea", max=max, required=required, hint=hint)


def asset(key, label, hint=None):
    return _f(key, label, "asset", hint=hint)


def lst(key, label, fields, max_items, hint=None):
    return _f(key, label, "list", fields=fields, max_items=max_items, hint=hint)


def strings(key, label, max_items, max=60, hint=None):
    return _f(key, label, "strings", max_items=max_items, max=max, hint=hint)


def select(key, label, options):
    return _f(key, label, "select", options=options)


def heading(default_max=90):
    return text("heading", "Heading", default_max, required=True)


SECTION_TYPES: dict[str, dict] = {
    "hero": {"label": "Hero", "fields": [text("eyebrow", "Small label above the heading", 60), text("heading", "Heading", 100, True), area("subheading", "Sub-heading", 300), asset("image", "Main image")]},
    "about": {"label": "About", "fields": [heading(), area("body", "Text", 1500, True, "Separate paragraphs with a blank line."), asset("image", "Image"), strings("highlights", "Short highlights", 6, 60)]},
    "services": {"label": "Services", "fields": [heading(), area("intro", "Introduction", 300),
                 lst("items", "Services", [text("title", "Name", 80, True), area("description", "Description", 300), text("price", "Price (optional)", 30), asset("image", "Image")], 12)]},
    "price_menu": {"label": "Price menu", "fields": [heading(), area("intro", "Introduction", 300),
                   lst("groups", "Groups", [text("title", "Group name", 60, True), lst("items", "Items", [text("name", "Name", 80, True), text("price", "Price", 30), text("note", "Note", 80)], 20)], 8)]},
    "menu": {"label": "Menu", "fields": [heading(), area("intro", "Introduction", 300),
             lst("categories", "Categories", [text("title", "Category", 60, True),
                 lst("items", "Dishes", [text("name", "Name", 80, True), text("description", "Description", 160), text("price", "Price", 30),
                                         select("veg", "Marker", ["", "veg", "nonveg", "egg"])], 30)], 10)]},
    "credentials": {"label": "Credentials", "fields": [heading(), lst("items", "Qualifications", [text("title", "Title", 100, True), text("detail", "Detail", 200)], 10)]},
    "conditions": {"label": "Conditions treated", "fields": [heading(), area("intro", "Introduction", 300), strings("items", "Conditions", 24, 60)]},
    "process": {"label": "Process", "fields": [heading(), area("intro", "Introduction", 300), lst("steps", "Steps", [text("title", "Step", 80, True), area("detail", "Detail", 250)], 8)]},
    "faqs": {"label": "Questions and answers", "fields": [heading(), lst("items", "Questions", [text("question", "Question", 160, True), area("answer", "Answer", 600, True)], 12)]},
    "gallery": {"label": "Gallery", "fields": [heading(), lst("images", "Images", [asset("asset", "Image"), text("caption", "Caption", 100)], 16, "Every image needs alt text before the site can be published.")]},
    "team": {"label": "Team", "fields": [heading(), area("intro", "Introduction", 300),
             lst("members", "People", [text("name", "Name", 80, True), text("role", "Role", 80), area("bio", "Short bio", 300), asset("image", "Photo")], 8)]},
    "offers": {"label": "Offers", "fields": [heading(), lst("items", "Offers", [text("title", "Offer", 80, True), area("detail", "Detail", 250), text("valid_until", "Valid until", 40)], 8)]},
    "products": {"label": "Product categories", "fields": [heading(), area("intro", "Introduction", 300),
                 lst("categories", "Categories", [text("title", "Category", 60, True), area("detail", "Detail", 200), asset("image", "Image")], 12)]},
    "featured": {"label": "Featured products", "fields": [heading(), area("intro", "Introduction", 300),
                 lst("items", "Products", [text("name", "Name", 80, True), area("detail", "Detail", 200), text("price", "Price", 30), asset("image", "Image")], 12)]},
    "areas": {"label": "Areas served", "fields": [heading(), area("intro", "Introduction", 300), strings("areas", "Areas", 40, 40)]},
    "trust": {"label": "Trust indicators", "fields": [heading(), lst("items", "Points", [text("title", "Title", 60, True), area("detail", "Detail", 200)], 8)]},
    "practice": {"label": "Practice areas", "fields": [heading(), area("intro", "Introduction", 300), lst("items", "Areas", [text("title", "Title", 80, True), area("detail", "Detail", 300)], 10)]},
    "hours": {"label": "Opening hours", "fields": [heading(), text("note", "Note under the hours", 160)]},
    "location": {"label": "Location and directions", "fields": [heading(), text("note", "Note (parking, landmark)", 200)]},
    "contact": {"label": "Contact and enquiry", "fields": [heading(), area("intro", "Introduction", 300), _f("show_enquiry", "Show the enquiry form", "bool"), _f("whatsapp_optin", "Offer \"updates on WhatsApp\" on the enquiry form (needs WhatsApp automation)", "bool")]},
    "disclaimer": {"label": "Health disclaimer", "fields": [heading(), area("text", "Text", 500, True)]},
    "cta_band": {"label": "Call-to-action band", "fields": [text("heading", "Heading", 100, True), text("text", "Text", 200)]},
}

BUSINESS_FIELDS = [
    text("name", "Business name", 120, True), text("tagline", "Tagline", 140), _f("phone", "Phone", "phone"), _f("whatsapp", "WhatsApp number (if different)", "phone"),
    _f("email", "Email", "email"), area("address", "Address", 300), text("city", "City", 100), _f("maps_url", "Google Maps link", "url", link="maps", max=500),
    _f("review_url", "Google review link", "url", link="review", max=1000), _f("order_url", "Ordering or booking link", "url", link="order", max=500),
    _f("instagram", "Instagram", "url", link="social", max=300), _f("facebook", "Facebook", "url", link="social", max=300), _f("youtube", "YouTube", "url", link="social", max=300),
    text("whatsapp_message", "Message a WhatsApp enquiry starts with", 120), asset("logo", "Logo"),
]
CTA_KINDS = ["call", "whatsapp", "enquiry", "directions", "order"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _t(key, label, description, keywords, hero, sections, extra, cta, accent) -> dict:
    return {"key": key, "label": label, "description": description, "keywords": keywords, "hero": hero, "default_sections": sections, "extra_allowed": extra, "cta": cta, "accent": accent,
            "version": TEMPLATE_VERSION}


# Every template has a different hero and a different set and order of sections; render.py gives each its own layout. Starting text is neutral and makes no claims about the business.
TEMPLATES: dict[str, dict] = {t["key"]: t for t in [
    _t("clinic", "Clinic and physiotherapy", "Appointment-first. Credentials, conditions treated, treatment process, FAQs and a health disclaimer.",
       ("clinic", "hospital", "physio", "dental", "doctor", "health", "pharmacy", "medical", "therapy", "diagnostic", "ayurved", "homeo", "skin"), "appointment",
       [("hero", {"eyebrow": "Appointments"}), ("trust", {"heading": "Why patients choose us"}), ("credentials", {"heading": "Qualifications"}), ("conditions", {"heading": "Conditions we treat"}),
        ("services", {"heading": "Treatments and services"}), ("process", {"heading": "What to expect"}), ("gallery", {"heading": "The clinic"}), ("faqs", {"heading": "Common questions"}),
        ("contact", {"heading": "Book an appointment", "show_enquiry": True}), ("disclaimer", {"heading": "Please note", "text": "The information on this website is general and does not replace a medical consultation. Results differ from person to person."})],
       ["about", "team", "offers", "hours", "location", "cta_band"], {"primary": ("enquiry", "Book an appointment"), "secondary": ("call", "Call the clinic")}, "teal"),
    _t("salon", "Salon and beauty", "Photography-led. Price menu, stylists, gallery, offers and WhatsApp booking.",
       ("salon", "beauty", "spa", "parlour", "parlor", "barber", "hair", "makeup", "nail", "wellness", "massage"), "photo",
       [("hero", {"eyebrow": "Book your visit"}), ("price_menu", {"heading": "Services and prices"}), ("team", {"heading": "Our stylists"}), ("gallery", {"heading": "Our work"}),
        ("offers", {"heading": "Offers"}), ("hours", {"heading": "Opening hours"}), ("contact", {"heading": "Book on WhatsApp", "show_enquiry": True})],
       ["about", "services", "faqs", "location", "cta_band"], {"primary": ("whatsapp", "Book on WhatsApp"), "secondary": ("call", "Call us")}, "purple"),
    _t("restaurant", "Restaurant and cafe", "Food-led. Menu with veg and non-veg markers, opening hours, gallery, directions and an order or call button.",
       ("restaurant", "cafe", "café", "bakery", "sweet", "food", "dhaba", "kitchen", "caterer", "bar", "juice", "ice cream", "mithai", "tiffin"), "food",
       [("hero", {"eyebrow": "Welcome"}), ("menu", {"heading": "Menu"}), ("hours", {"heading": "Opening hours"}), ("gallery", {"heading": "From our kitchen"}), ("location", {"heading": "Find us"}),
        ("contact", {"heading": "Order or reserve", "show_enquiry": True})],
       ["about", "offers", "faqs", "cta_band"], {"primary": ("call", "Call to order"), "secondary": ("directions", "Get directions")}, "orange"),
    _t("retail", "Retail store", "A store introduction, product categories, featured products, offers and the store location. No shopping cart.",
       ("store", "shop", "grocery", "clothing", "footwear", "electronics", "mobile", "retail", "supermarket", "jewel", "furniture", "stationery", "garment", "boutique", "hardware", "gift"), "intro",
       [("hero", {"eyebrow": "Visit the store"}), ("about", {"heading": "About the store"}), ("products", {"heading": "What we sell"}), ("featured", {"heading": "Featured"}),
        ("offers", {"heading": "Offers"}), ("gallery", {"heading": "In the store"}), ("location", {"heading": "Store location"}), ("hours", {"heading": "Opening hours"}),
        ("contact", {"heading": "Contact the store", "show_enquiry": True})],
       ["services", "faqs", "team", "cta_band"], {"primary": ("directions", "Visit the store"), "secondary": ("call", "Call the store")}, "red"),
    _t("home_services", "Home services", "Service-first. Areas served, services with indicative prices, how it works, trust points and a call or WhatsApp button.",
       ("plumb", "electric", "repair", "clean", "pest", "paint", "carpent", "ac ", "appliance", "home service", "cleaning", "movers", "laundry"), "service",
       [("hero", {"eyebrow": "Fast, reliable service"}), ("services", {"heading": "Services and indicative prices"}), ("areas", {"heading": "Areas we serve"}), ("process", {"heading": "How it works"}),
        ("trust", {"heading": "Why choose us"}), ("gallery", {"heading": "Our work"}), ("faqs", {"heading": "Questions"}), ("contact", {"heading": "Call or message us", "show_enquiry": True})],
       ["about", "offers", "team", "hours", "cta_band"], {"primary": ("call", "Call now"), "secondary": ("whatsapp", "WhatsApp us")}, "blue"),
    _t("professional", "Professional services", "Practice areas, credentials, about, process, FAQs and a consultation call-to-action.",
       ("lawyer", "advocate", "account", "consult", "architect", "finance", "insurance", "tax", "audit", "agency", "professional", "real estate", "school", "education", "training", "hotel", "guest house", "gym", "yoga", "fitness", "coach", "tutor"), "practice",
       [("hero", {"eyebrow": "Consultations"}), ("practice", {"heading": "Practice areas"}), ("credentials", {"heading": "Credentials"}), ("about", {"heading": "About"}), ("process", {"heading": "How we work"}),
        ("faqs", {"heading": "Common questions"}), ("contact", {"heading": "Book a consultation", "show_enquiry": True})],
       ["services", "team", "gallery", "hours", "location", "cta_band", "offers", "trust"], {"primary": ("enquiry", "Book a consultation"), "secondary": ("call", "Call us")}, "navy"),
]}


def allowed_sections(template_key: str) -> list[str]:
    t = TEMPLATES[template_key]
    out = [s for s, _ in t["default_sections"]]
    for s in t["extra_allowed"]:
        if s not in out:
            out.append(s)
    return out


def suggest_template(category: str | None) -> str:
    """The template whose keywords best match the business category; the professional template when nothing matches."""
    c = (category or "").lower()
    best, score = "professional", 0
    for key, t in TEMPLATES.items():
        n = sum(1 for k in t["keywords"] if k in c)
        if n > score:
            best, score = key, n
    return best


def _short_id(i: int, prefix: str) -> str:
    return f"{prefix}{i:02d}"


def default_content(template_key: str, biz: dict) -> dict:
    """The starting draft for a template, filled from the business record. `biz`: name, category, city, phone, email, address, review_url, maps_url, whatsapp. Lists start empty, so a site
    cannot be published until an administrator has written the real content (the publish check names every empty section)."""
    t = TEMPLATES[template_key]
    name = (biz.get("name") or "Your business").strip()[:120]
    city, cat = (biz.get("city") or "").strip(), (biz.get("category") or "").strip()
    where = f"{cat} in {city}" if cat and city else cat or (f"in {city}" if city else "")
    sections = []
    for i, (typ, data) in enumerate(t["default_sections"], 1):
        d = {f["key"]: ([] if f["kind"] in ("list", "strings") else None if f["kind"] == "asset" else False if f["kind"] == "bool" else "") for f in SECTION_TYPES[typ]["fields"]}
        d.update(data)
        if typ == "hero":
            d.update({"heading": name, "subheading": where})
        sections.append({"id": _short_id(i, "s"), "type": typ, "enabled": True, "data": d})
    p, s = t["cta"]["primary"], t["cta"].get("secondary")
    title = f"{name} | {where}" if where else name
    return {
        "business": {"name": name, "tagline": where, "phone": biz.get("phone") or "", "whatsapp": biz.get("whatsapp") or "", "email": biz.get("email") or "", "address": biz.get("address") or "",
                     "city": city, "maps_url": biz.get("maps_url") or "", "review_url": biz.get("review_url") or "", "order_url": "", "instagram": "", "facebook": "", "youtube": "",
                     "whatsapp_message": f"Hello {name}, I found you online and have a question.", "logo": None,
                     "hours": [{"day": d, "closed": False, "open": "", "close": ""} for d in DAYS]},
        "cta": {"primary": {"kind": p[0], "label": p[1]}, "secondary": {"kind": s[0], "label": s[1]} if s else None},
        "seo": {"title": title[:70], "description": (f"{name}{', ' + where if where else ''}. Call or send an enquiry." )[:160], "og_image": None},
        "theme": {"accent": t["accent"]},
        "sections": sections,
    }


def catalogue() -> dict:
    """What the admin editor needs: templates, section specs, accents, call-to-action kinds."""
    return {"templates": [{"key": t["key"], "label": t["label"], "description": t["description"], "version": t["version"], "accent": t["accent"], "hero": t["hero"],
                           "sections": [s for s, _ in t["default_sections"]], "allowed_sections": allowed_sections(t["key"])} for t in TEMPLATES.values()],
            "section_types": {k: {"label": v["label"], "fields": v["fields"]} for k, v in SECTION_TYPES.items()},
            "business_fields": BUSINESS_FIELDS, "accents": ACCENTS, "cta_kinds": CTA_KINDS, "days": DAYS, "max_sections": MAX_SECTIONS}
