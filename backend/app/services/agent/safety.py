"""Grounding and safety for AI-written public text (replies, posts, profile text).

Two layers, because a prompt is a request, not a guarantee:
  1. the model is told what it may say (the Knowledge Base) and what it may not;
  2. the output is then CHECKED by deterministic rules here. A draft that breaks a rule is not shown as a normal draft.

The checks are deliberately conservative and English/Hinglish-aware. They reduce risk; they do not replace the owner's review,
which is always required before anything is published.
"""
import re
from dataclasses import dataclass

HEALTH_WORDS = ("physio", "clinic", "doctor", "dental", "dentist", "hospital", "health", "medical", "therapy", "ayurved", "homeopath", "chiropract",
                "orthop", "dermat", "pediatric", "paediatric", "gynae", "gynec", "eye care", "optical", "diagnostic", "pathology", "wellness", "nursing", "pharmacy")

# Seeded for health businesses. The owner can add to or remove from this list on the Knowledge Base page.
HEALTH_PROHIBITED_DEFAULTS = [
    "guaranteed cure", "100% cure", "100% recovery", "complete cure", "permanent cure", "miracle", "painless treatment", "pain-free guaranteed",
    "instant relief", "permanent relief", "no side effects", "best doctor in", "number 1 clinic", "no.1 clinic", "risk-free",
    "we treated you", "your treatment", "your diagnosis", "your condition", "your appointment on", "your medical records", "as our patient",
]

# Patterns that are never acceptable in a public reply to a health-business review (confirming a patient, treatment details, promises).
_HEALTH_PATTERNS = [
    (r"\b(as|since|being) (you|your)\b.{0,25}\b(patient|client)\b", "confirms the reviewer is a patient"),
    (r"\bwe (treated|saw|examined|diagnosed|operated|prescribed)\b", "refers to treating the reviewer"),
    (r"\byour (treatment|therapy|session|diagnosis|condition|injury|surgery|prescription|medication|recovery|scan|report|appointment)\b", "refers to the reviewer's treatment"),
    (r"\b(cure[sd]?|guarantee[sd]?|guaranteed)\b", "promises an outcome"),
    (r"\b100\s?%", "makes an absolute claim"),
    (r"\b(painless|pain-free|risk-free|no side[- ]effects?)\b", "makes a safety claim"),
    (r"\b(will|would|can) (heal|recover|fix|cure|get rid of|eliminate)\b", "promises an outcome"),
    (r"\bresults? (in|within) \d+", "promises a timeline"),
    (r"\b(permanent|instant|miracle)\b", "makes an outcome claim"),
]
_PRICE = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:₹|rs\b|inr\b|rupees?\b|/-)", re.I)
_DISCOUNT = re.compile(r"\b\d{1,3}\s?%\s*(?:off|discount)\b|\b(?:flat|upto|up to)\s+\d+\s?%|\bfree\s+(?:consultation|session|checkup|check-up|trial|assessment|screening)\b|\b(?:buy|get)\s+\d+\s+(?:get|free)\b", re.I)
_BOOKING = re.compile(r"\b(your )?(appointment|booking|slot)\b.{0,20}\b(is|has been|have been|confirmed|booked)\b|\bwe(?:'ve| have) booked\b", re.I)


@dataclass
class Violation:
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def is_health(category: str | None) -> bool:
    c = (category or "").lower()
    return any(w in c for w in HEALTH_WORDS)


def _norm_amount(s: str) -> str:
    return re.sub(r"[,\s]", "", s).rstrip("0").rstrip(".") if "." in s else re.sub(r"[,\s]", "", s)


def allowed_amounts(offers: list[dict]) -> set[str]:
    out: set[str] = set()
    for o in offers or []:
        p = o.get("price_inr")
        if p not in (None, ""):
            out.add(_norm_amount(str(p)))
    return out


def check_text(text: str, *, kb: dict, kind: str) -> list[Violation]:
    """kb: {offers, prohibited_claims, approved_claims, safety_profile}. kind: reply | post | profile | review_reply.
    Returns [] when the text passes every rule."""
    v: list[Violation] = []
    t = text or ""
    low = t.lower()
    for phrase in kb.get("prohibited_claims") or []:
        if phrase and phrase.strip().lower() in low:
            v.append(Violation("prohibited_claim", f"Contains a phrase you marked as not allowed: “{phrase.strip()}”."))
    offers = kb.get("offers") or []
    ok = allowed_amounts(offers)
    for m in _PRICE.finditer(t):
        amount = _norm_amount(m.group(1) or m.group(2) or "")
        if amount and amount not in ok:
            v.append(Violation("invented_price", f"Mentions a price (₹{amount}) that is not in your verified prices."))
    if _DISCOUNT.search(t) and not any(o.get("name") and o["name"].strip().lower() in low for o in offers):
        v.append(Violation("invented_offer", "Mentions a discount or free offer that is not in your verified offers."))
    if _BOOKING.search(t):
        v.append(Violation("appointment_claim", "Says an appointment or booking is confirmed; the assistant cannot confirm bookings."))
    if kb.get("safety_profile") == "health" or kind == "reply" and kb.get("safety_profile") == "health":
        approved = [a.strip().lower() for a in (kb.get("approved_claims") or []) if a.strip()]
        for pat, why in _HEALTH_PATTERNS:
            for m in re.finditer(pat, t, re.I):
                if any(a in m.group(0).lower() or m.group(0).lower() in a for a in approved):
                    continue  # the owner explicitly approved this wording
                v.append(Violation("health_claim", f"Not allowed for a health business: it {why} (“{m.group(0).strip()}”)."))
                break
    seen, out = set(), []
    for x in v:  # one entry per distinct message
        if x.message not in seen:
            seen.add(x.message)
            out.append(x)
    return out
