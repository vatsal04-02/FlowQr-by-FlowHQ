"""Deterministic sensitivity flags for review replies. These force human handling in the UI."""
import re
from dataclasses import dataclass, field

CATEGORIES: dict[str, list[str]] = {
    "medical": [
        r"diagnos", r"surgery", r"operation", r"treatment", r"medicine", r"prescri", r"infection", r"side effect",
        r"injur", r"misdiagnos", r"patient", r"fracture", r"dawai", r"ilaaj", r"ilaj", r"इलाज", r"दवा", r"ऑपरेशन",
        r"worse", r"pain", r"dard", r"दर्द",
    ],
    "legal": [
        r"lawyer", r"legal", r"\bsue\b", r"lawsuit", r"court", r"consumer forum", r"consumer court", r"police",
        r"\bfir\b", r"vakeel", r"वकील", r"कोर्ट", r"पुलिस", r"case (kar|file)", r"defamation", r"negligen",
    ],
    "threat": [
        r"\bkill\b", r"threat", r"destroy you", r"will (burn|ruin|expose)", r"dekh lunga", r"dekh lenge", r"maar", r"धमकी",
        r"shut (you|this) down", r"report you",
    ],
    "accusation": [
        r"fraud", r"scam", r"cheat", r"dhokha", r"धोखा", r"stole", r"theft", r"harass", r"assault", r"molest",
        r"overcharg", r"fake", r"lied", r"lie ", r"rude", r"bad behaviou?r", r"misbehav", r"discriminat", r"corrupt",
    ],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in CATEGORIES.items()}

REASON_TEXT = {
    "medical": "Mentions medical or treatment details. Do not confirm patient status or discuss care in public.",
    "legal": "Mentions legal action or authorities. Consider review by the owner or legal advisor before replying.",
    "threat": "Contains a threat. Handle personally; consider reporting to Google.",
    "accusation": "Contains an accusation (fraud, rudeness, overcharging...). Investigate before replying.",
    "low_rating": "Low rating. Review the complaint personally before approving a reply.",
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# Structural signals (not keywords). A review can be risky with none of the flagged words: a low rating, a long angry account, someone's personal
# data in the text, shouting. These raise the level on their own.
# ---------------------------------------------------------------------------------------------------------------------------------------------
_PRIVACY_PATTERNS = [re.compile(p, re.I) for p in (
    r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)",  # an Indian mobile number
    r"[\w.+-]+@[\w-]+\.[\w.-]+",  # an email address
    r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)",  # an Aadhaar-shaped number
    r"\b[A-Z]{5}\d{4}[A-Z]\b",  # a PAN-shaped number
    r"\b(privacy|data (leak|breach)|leaked|aadhaar|aadhar)\b", r"\bshared my (photo|photos|number|details|data|report|reports|records)\b",
    r"\bwithout (my |their )?(consent|permission)\b", r"\b(recorded|filmed|photographed) (me|us|my)\b", r"\bcctv\b", r"\bmy (medical )?records\b",
)]
_SELF_HARM = re.compile(r"suicid|kill myself|end my life|want to die|self[- ]harm|aatmahatya|आत्महत्या", re.I)
_PROFANITY = re.compile(r"\b(f+u+c+k\w*|shit\w*|bastard|asshole|bloody (fool|idiot)|madarchod|bhenchod|chutiya|harami|kutta|kamina|saala)\b", re.I)
HIGH_REASONS = frozenset({"threat", "legal", "privacy", "self_harm", "harassment", "extortion", "defamation"})
LOW_RATING_ESCALATES = frozenset({"medical", "accusation", "hostile_tone", "detailed_complaint", "discrimination", "spam_or_fake", "other_sensitive"})

REASON_TEXT.update({
    "privacy": "Contains personal details or a privacy complaint. Do not repeat anything personal in public; reply briefly and take it offline.",
    "self_harm": "Mentions self-harm. Do not reply from a template: handle it personally and with care.",
    "hostile_tone": "Hostile tone or abusive language. Reply calmly, or consider reporting it to Google if it breaks their rules.",
    "detailed_complaint": "A long, detailed complaint. Read it fully and check the facts before replying.",
    "harassment": "Describes harassment. Handle personally; do not argue in public.",
    "extortion": "Looks like pressure for money, a refund or a favour in return for a better review. Do not engage publicly; consider reporting it.",
    "discrimination": "Raises discrimination. Take it seriously and reply personally.",
    "defamation": "Makes serious claims about named people or the business. Consider advice before replying.",
    "spam_or_fake": "May be spam or a fake review. Consider reporting it to Google instead of replying.",
    "other_sensitive": "The AI safety check found something sensitive. Read it before replying.",
})


@dataclass
class Risk:
    """How risky replying to this review is. `level` low|medium|high; `reasons` the codes shown to the owner (the same codes as before, plus the new ones);
    `ai_checked` True only when the AI safety check actually ran and answered; `ai_failed` True when it was expected but could not run (never treated as "safe")."""

    level: str = "low"
    reasons: list[str] = field(default_factory=list)
    ai_checked: bool = False
    ai_failed: bool = False

    def needs_human(self) -> bool:
        return self.level != "low" or bool(self.reasons)


def level_for(reasons: list[str], rating: int, text: str) -> str:
    level = "medium" if reasons else "low"
    if any(r in HIGH_REASONS for r in reasons):
        level = "high"
    if rating <= 2 and any(r in LOW_RATING_ESCALATES for r in reasons):
        level = "high"
    if rating <= 2 and len(text) >= 300:
        level = "high"
    return level


def assess_risk(text: str | None, rating: int, category: str | None = None) -> Risk:
    """Deterministic risk, from the words AND the shape of the review. Pure and testable."""
    body = (text or "").strip()
    reasons: list[str] = []
    for name, patterns in _COMPILED.items():
        if any(p.search(body) for p in patterns):
            # "pain"/"patient" in a happy review is not a red flag for a physio clinic: only flag
            # medical keywords on low/neutral ratings or when clearly clinical.
            if name == "medical" and rating >= 4:
                continue
            reasons.append(name)
    if any(p.search(body) for p in _PRIVACY_PATTERNS):
        reasons.append("privacy")
    if _SELF_HARM.search(body):
        reasons.append("self_harm")
    letters = [c for c in body if c.isalpha()]
    shouting = len(letters) >= 25 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6
    if _PROFANITY.search(body) or shouting or re.search(r"[!?]{4,}", body):
        reasons.append("hostile_tone")
    if rating <= 2:
        reasons.append("low_rating")  # a 1-2 star review is always read by a person first, with or without flagged words
    if rating <= 3 and len(body) >= 300:
        reasons.append("detailed_complaint")
    if len(body) > 1500 and "detailed_complaint" not in reasons:
        reasons.append("detailed_complaint")
    return Risk(level=level_for(reasons, rating, body), reasons=reasons)


def assess_review(text: str | None, rating: int, category: str | None = None) -> list[str]:
    """Reason codes; non-empty means human handling is required. Kept for existing callers: see `assess_risk` for the level."""
    return assess_risk(text, rating, category).reasons


def eligible_for_auto_reply(risk: Risk, *, require_ai_check: bool = True) -> bool:
    """Whether an ordinary review could be answered without a person, IF an owner has turned automatic replies on (nothing does that today).
    Only a LOW-risk review with no reasons qualifies, and by default only when the AI safety check also ran and agreed: an unchecked review is never
    treated as safe for automation."""
    if risk.level != "low" or risk.reasons:
        return False
    return risk.ai_checked or not require_ai_check
