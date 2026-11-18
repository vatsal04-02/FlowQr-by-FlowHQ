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
}


def wording_for(purpose: str, business_name: str, version: str = WORDING_VERSION) -> str:
    template = WORDINGS.get((purpose, version))
    if template is None:
        raise KeyError(f"unknown consent wording {purpose}/{version}")
    return template.format(business=(business_name or "this business").strip()[:120])[:600]


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
    "whatsapp_starter": {"label": "WhatsApp Starter", "price_inr_month": 299, "automation_limit": 3, "campaigns": False, "segmentation": "none",
                         "summary": "3 automations: reminders and review follow-ups."},
    "whatsapp_growth": {"label": "WhatsApp Growth", "price_inr_month": 499, "automation_limit": 8, "campaigns": True, "segmentation": "basic",
                        "summary": "8 automations, scheduled campaigns and simple customer groups."},
    "whatsapp_pro": {"label": "WhatsApp Pro", "price_inr_month": 799, "automation_limit": 15, "campaigns": True, "segmentation": "advanced",
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
    {"key": "birthday", "title": "Birthday and festival wishes", "purpose": "marketing", "phase": 4, "live": False,
     "description": "A short greeting on a customer's special day, only for customers who agreed to receive updates.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to receive offers"]},
    {"key": "winback", "title": "Bring back customers who stopped visiting", "purpose": "marketing", "phase": 4, "live": False,
     "description": "Message customers who have not visited for a time you choose, only if they agreed to receive updates.",
     "needs": ["A connected WhatsApp number", "Customers who agreed to receive offers"]},
]
