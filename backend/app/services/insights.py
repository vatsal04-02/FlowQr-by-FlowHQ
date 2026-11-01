"""Review sentiment + recurring topics. Deterministic keyword/rating heuristic (EN / Hinglish / Hindi).

This is intentionally transparent and cheap: it needs no AI quota and can be audited. It is a *signal*, not ground truth.
"""
import re
from collections import Counter, defaultdict

TOPICS: dict[str, tuple[str, list[str]]] = {
    "wait_time": ("Waiting time", [r"\bwait", r"\blate\b", r"\bdelay", r"\bqueue", r"\bintezaar", r"\binterzar", r"\bder\b", r"इंतज़ार", r"इंतजार", r"देर"]),
    "staff": ("Staff & reception", [r"\bstaff", r"reception", r"behaviou?r", r"\brude", r"\bpolite", r"\bhelpful", r"\bfriendly", r"\bnurse", r"\bcourteous", r"स्टाफ", r"व्यवहार"]),
    "doctor": ("Doctor / therapist", [r"\bdoctor", r"\bdr\.?\s", r"\bphysio", r"therapist", r"dentist", r"\bexpert", r"\bknowledgeable", r"\bexperienced", r"डॉक्टर"]),
    "results": ("Treatment results", [r"\bpain", r"\brelief", r"\brecover", r"\bimprov", r"\bcured", r"\bhealed", r"\baaram", r"\bdard", r"आराम", r"दर्द", r"\bbetter\b", r"\bresults?\b"]),
    "cleanliness": ("Cleanliness & hygiene", [r"\bclean", r"hygien", r"\bdirty", r"steril", r"\bsaaf", r"\bgandg", r"साफ", r"गंदगी"]),
    "pricing": ("Pricing & value", [r"\bprice", r"\bcost", r"\bfees?\b", r"expensive", r"costly", r"\bcharges?", r"afford", r"value for money", r"overcharg", r"\bmehang", r"महंगा", r"पैसे"]),
    "booking": ("Appointments & booking", [r"appointment", r"\bbooking", r"\bbooked", r"\bslot", r"\bschedul", r"walk-?in"]),
    "ambience": ("Ambience & facilities", [r"ambien", r"atmospher", r"parking", r"\bmusic", r"\bspacious", r"\bcrowd", r"seating", r"\bAC\b", r"interior"]),
    "food": ("Food & drinks", [r"\bfood", r"\btaste", r"\bmenu", r"\bdish", r"delicious", r"\bcoffee", r"\bchai\b", r"\bmeal"]),
    "communication": ("Communication", [r"\bexplain", r"\blisten", r"\bunderstood", r"\bcommunicat", r"\bsamjha", r"समझाया", r"\bcounsel"]),
}
_TOPICS_RE = {k: (label, [re.compile(p, re.I) for p in pats]) for k, (label, pats) in TOPICS.items()}

POS = [r"\bgreat", r"\bexcellent", r"\bamazing", r"\bwonderful", r"\bbest\b", r"\bgood\b", r"\bnice", r"\bkind", r"\bthank", r"\brecommend",
       r"\bhappy", r"\bsatisf", r"\bprofessional", r"\bbadhiya", r"\bzabardast", r"\baccha", r"\bacha\b", r"\bbehtareen", r"बहुत अच्छ", r"शानदार", r"धन्यवाद"]
NEG = [r"\bbad\b", r"\bworst", r"\bpoor", r"\brude", r"\bterrible", r"\bawful", r"\bdisappoint", r"\bunhappy", r"\bnot (good|happy|satisf)",
       r"\bwaste", r"\bwait(ed|ing)? (for )?(too|very|long|an? hour)", r"\boverpriced", r"\bdirty", r"\bnever\b", r"\bbakwas", r"\bghatiya", r"\bkharab", r"बकवास", r"खराब", r"घटिया"]
_POS = [re.compile(p, re.I) for p in POS]
_NEG = [re.compile(p, re.I) for p in NEG]


def sentiment(rating: int, text: str | None) -> str:
    """Rating dominates; text only breaks ties on 3 stars or flags clear contradictions."""
    t = text or ""
    pos = sum(1 for p in _POS if p.search(t))
    neg = sum(1 for p in _NEG if p.search(t))
    if rating >= 4:
        return "negative" if neg >= 3 and neg > pos + 1 else "positive"
    if rating <= 2:
        return "positive" if pos >= 3 and pos > neg + 1 else "negative"
    return "positive" if pos > neg else "negative" if neg > pos else "neutral"


def topics_in(text: str | None) -> list[str]:
    t = text or ""
    return [k for k, (_, pats) in _TOPICS_RE.items() if any(p.search(t) for p in pats)]


def analyse(reviews: list[tuple[int, str | None]], previous: list[tuple[int, str | None]] | None = None, sample_len: int = 140) -> dict:
    mix = Counter()
    per_topic: dict[str, dict] = defaultdict(lambda: {"mentions": 0, "positive": 0, "neutral": 0, "negative": 0, "ratings": [], "sample": None, "sample_rating": None})
    for rating, text in reviews:
        s = sentiment(rating, text)
        mix[s] += 1
        for k in topics_in(text):
            d = per_topic[k]
            d["mentions"] += 1
            d[s] += 1
            d["ratings"].append(rating)
            if d["sample"] is None or (s == "negative" and d["sample_rating"] and d["sample_rating"] > rating):
                d["sample"], d["sample_rating"] = (text or "")[:sample_len], rating
    prev_counts = Counter(k for _, text in (previous or []) for k in topics_in(text))
    topics = []
    for k, d in per_topic.items():
        topics.append({
            "topic": k, "label": TOPICS[k][0], "mentions": d["mentions"], "positive": d["positive"], "neutral": d["neutral"], "negative": d["negative"],
            "avg_rating": round(sum(d["ratings"]) / len(d["ratings"]), 2), "previous_mentions": prev_counts.get(k, 0), "sample": d["sample"],
        })
    topics.sort(key=lambda x: (-x["mentions"], x["label"]))
    return {"total_reviews": len(reviews), "reviews_with_text": sum(1 for _, t in reviews if (t or "").strip()),
            "sentiment": {"positive": mix["positive"], "neutral": mix["neutral"], "negative": mix["negative"]}, "topics": topics,
            "method": "Keyword and star-rating heuristic (English, Hinglish, Hindi). Treat as a guide, not a verdict."}
