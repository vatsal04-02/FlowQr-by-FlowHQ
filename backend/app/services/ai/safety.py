"""Deterministic sensitivity flags for review replies. These force human handling in the UI."""
import re

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


def assess_review(text: str | None, rating: int, category: str | None = None) -> list[str]:
    """Return a list of reason codes; non-empty means human handling is required."""
    reasons: list[str] = []
    body = text or ""
    for name, patterns in _COMPILED.items():
        if any(p.search(body) for p in patterns):
            # "pain"/"patient" in a happy review is not a red flag for a physio clinic: only flag
            # medical keywords on low/neutral ratings or when clearly clinical.
            if name == "medical" and rating >= 4:
                continue
            reasons.append(name)
    if rating <= 2 and reasons:
        reasons.append("low_rating")
    return reasons
