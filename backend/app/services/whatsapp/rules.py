"""WhatsApp automation: the rules that are data (consent wording, opt-out words, add-on tiers, the automation catalogue). Kept in one place so the API, the screens and the tests agree."""
import hashlib
import hmac
import re
import uuid

from app.core.config import settings

# ---- consent wording. A consent is stored with the exact text and its version; changing a sentence means a NEW version, never an edit of an old one.
WORDING_VERSION = "2026-11-19.1"
WORDINGS = {
    ("marketing", WORDING_VERSION): "I agree to receive offers and updates from {business} on WhatsApp. I can reply STOP at any time to stop them.",
    ("utility", WORDING_VERSION): "I agree to receive messages about my visit, booking or enquiry with {business} on WhatsApp.",
    ("occasion", WORDING_VERSION): "I agree to receive birthday and festival greetings from {business} on WhatsApp. I can reply STOP at any time to stop them.",
}


def wording_for(purpose: str, business_name: str, version: str = WORDING_VERSION) -> str:
    template = WORDINGS.get((purpose, version))
    if template is None:
        raise KeyError(f"unknown consent wording {purpose}/{version}")
    return template.format(business=(business_name or "this business").strip()[:120])[:600]


# ---- opt-in without a phone number on the page. The customer sends a message; the message itself is the consent, so its wording is fixed here and compared exactly.
PURPOSE_WORDS = {"utility": "updates about your visits and enquiries", "marketing": "offers and updates", "both": "updates about your visits and enquiries, and offers"}
RESERVED_KEYWORDS = frozenset({"yes", "no", "ok", "okay", "hi", "hii", "hey", "hello", "thanks", "thank", "thankyou", "start", "help", "cancel", "end", "quit", "bye", "haan", "nahi"})
OPTIN_WORDING_VERSION = "optin-1"


def _biz(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "this business")).strip()[:40]


def optin_text(purpose: str, business: str | None, code: str) -> str:
    """The text a customer's WhatsApp is prefilled with after tapping the button on the QR page. It is also the consent wording, stored exactly."""
    b = _biz(business)
    if purpose == "marketing":
        return f"Yes, send me offers and updates from {b} on WhatsApp. I can reply STOP to stop them. Code: {code}"
    if purpose == "both":
        return f"Yes, send me updates about my visits and enquiries, and offers, from {b} on WhatsApp. I can reply STOP to stop offers. Code: {code}"
    return f"Yes, send me updates about my visits and enquiries from {b} on WhatsApp. Code: {code}"


def keyword_wording(keyword: str, purpose: str, business: str | None) -> str:
    """What texting an opt-in keyword means. The owner shows exactly this next to the keyword (a sign, a bill); it is stored as the consent wording."""
    b = _biz(business)
    stop = " I can reply STOP to stop offers." if purpose in ("marketing", "both") else ""
    return f'Texting "{keyword.upper()}" to {b} on WhatsApp means: I agree to receive {PURPOSE_WORDS[purpose]} from {b}.{stop}'


def norm_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def keyword_problem(keyword: str | None) -> str | None:
    k = (keyword or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]{3,20}", k):
        return "Use 3 to 20 letters or numbers, with no spaces."
    if k in RESERVED_KEYWORDS or k in OPT_OUT_WORDS:
        return "That word is too common or already means something else. Choose a more specific word."
    return None


# ---- opt-out: a customer's reply that means "stop messaging me" (exact message after trimming; a sentence that merely contains the word is NOT an opt-out)
OPT_OUT_WORDS = frozenset({"stop", "stop all", "stopall", "unsubscribe", "opt out", "optout", "opt-out", "बंद", "बंद करो", "band", "band karo"})


def is_opt_out(text: str | None) -> bool:
    if not text:
        return False
    t = re.sub(r"[\s.!]+$", "", re.sub(r"\s+", " ", text.strip().lower()))
    return t in OPT_OUT_WORDS


def phone_hash(tenant_id: uuid.UUID, phone: str) -> str:
    """Keyed hash of a number for the suppression list: stable per business, useless without the server's secret."""
    return hmac.new(settings.secret_key.encode(), f"wa-suppress:{tenant_id}:{phone}".encode(), hashlib.sha256).hexdigest()


# ---- add-on tiers. Prices are REFERENCE text (nothing is billed from the application). Meta's per-message charges are separate and never included in these.
ADDON_TIERS = {
    "whatsapp_starter": {"label": "WhatsApp Starter", "price_inr_month": 299, "automation_limit": 3, "campaigns": False, "occasions": False, "click_tracking": False, "segmentation": "none",
                         "summary": "3 automations: reminders and review follow-ups."},
    "whatsapp_growth": {"label": "WhatsApp Growth", "price_inr_month": 499, "automation_limit": 8, "campaigns": True, "occasions": True, "click_tracking": False, "segmentation": "basic",
                        "summary": "8 automations, scheduled campaigns and simple customer groups."},
    "whatsapp_pro": {"label": "WhatsApp Pro", "price_inr_month": 799, "automation_limit": 15, "campaigns": True, "occasions": True, "click_tracking": True, "segmentation": "advanced",
                     "summary": "15 automations, advanced customer groups and campaign results."},
}

# ---- the automation catalogue shown to owners. Plain words; `available` is False in Phase 1 (nothing sends yet).
CATALOGUE = [
    {"key": "review_followup", "title": "Get more customer reviews", "purpose": "utility", "phase": 3, "live": True,
     "description": "After a visit, send one neutral message asking the customer to share their honest experience, with your review link.",
     "needs": ["A connected WhatsApp number", "The customer agreed to messages about their visit"]},
    {"key": "enquiry_followup", "title": "Follow up with enquiries", "purpose": "utility", "phase": 3, "live": True,
     "description": "When someone contacts your business, send a quick thank-you and, if you have not replied, one gentle follow-up.",
     "needs": ["A connected WhatsApp number", "The customer agreed to messages about their enquiry"]},
    {"key": "offers", "title": "Send offers to customers", "purpose": "marketing", "phase": 4, "live": True,
     "description": "Send an offer to customers who agreed to receive updates. You see who will get it and the likely WhatsApp charge before anything is sent, and you approve it first.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to receive offers", "An approved message"]},
    {"key": "birthday", "title": "Birthday wishes", "purpose": "occasion", "phase": 2, "live": True,
     "description": "One short, neutral birthday greeting a year, between 9 am and 9 pm India time, only for customers who agreed to occasion greetings. It never contains an offer or discount.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to birthday and festival greetings and gave their birthday", "An approved greeting message"]},
    {"key": "festival", "title": "Festival wishes", "purpose": "occasion", "phase": 2, "live": True,
     "description": "A short greeting on the festivals you choose, between 9 am and 9 pm India time, only for customers who agreed to occasion greetings. It never contains an offer or discount.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to birthday and festival greetings", "An approved greeting message", "The festivals you want to greet"]},
    {"key": "winback", "title": "Bring back customers who stopped visiting", "purpose": "marketing", "phase": 4, "live": False,
     "description": "Message customers who have not visited for a time you choose, only if they agreed to receive updates.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to receive offers"]},
]


# ---- occasion greetings (birthday and festival). Greetings only: never an offer, never a discount, never outside 9 am to 9 pm India time.
OCCASION_START, OCCASION_END = 9, 21  # hours in India time; fixed, not a setting: a greeting is never sent outside them
OCCASION_HOURS = (OCCASION_START, OCCASION_END - 1)  # the hour an owner can choose: 9 am to 8 pm
OFFER_WORDS = frozenset({"offer", "offers", "discount", "discounts", "sale", "off", "free", "deal", "deals", "cashback", "coupon", "coupons", "voucher", "vouchers", "buy", "win", "gift", "gifts",
                         "bonus", "save", "price", "prices", "rs", "inr", "special", "limited", "exclusive", "book", "visit", "order"})


def greeting_name_problem(name: str | None) -> str | None:
    """A festival's name goes into a greeting, so it must be a plain name: letters, spaces, apostrophes and hyphens, and nothing that sounds like an offer."""
    n = re.sub(r"\s+", " ", (name or "")).strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z '\u2019-]{1,39}", n):
        return "Use 2 to 40 letters for the festival's name. Numbers and symbols are not allowed."
    if any(w in OFFER_WORDS for w in re.findall(r"[a-z]+", n.lower())):
        return "A greeting never mentions an offer or discount. Use only the festival's own name."
    return None


def in_occasion_hours(now) -> bool:
    """True from 9:00 up to (not including) 21:00 India time."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    t = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo("Asia/Kolkata"))
    return OCCASION_START <= t.hour < OCCASION_END
