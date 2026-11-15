"""Deterministic quality checks for AI-written public text (replies, posts, profile descriptions).

These are NOT safety rules (services/agent/safety.py blocks invented prices, health claims and so on). They measure whether the text is
something an owner would want to use: specific rather than boilerplate, different from what the business already published, written in
the requested language, free of keyword stuffing. They are cheap, repeatable and need no second model, so they are used three ways:

  1. at generation time: one targeted retry when a draft is clearly generic, repetitive or in the wrong language;
  2. in the evaluation harness (app/ai_eval): the same functions score every model on the same benchmark;
  3. in regression tests: a change to a prompt or a rule cannot silently make output worse.

Every function is pure (text in, numbers out). They are heuristics: they catch the common failures, they do not prove the text is good.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
HASHTAG = re.compile(r"(?<!\w)#\w+")
WORD = re.compile(r"[a-z0-9ऀ-ॿ']+", re.I)

# Boilerplate that marks text as machine-written marketing. Matched case-insensitively as phrases.
GENERIC_PHRASES = [
    "we are thrilled", "we're thrilled", "we are delighted", "we're delighted", "we are excited to", "we're excited to", "at our clinic, we", "at our salon, we",
    "at our restaurant, we", "at our gym, we", "at our store, we", "look no further", "in today's fast-paced", "in today's world", "your satisfaction is our priority",
    "your satisfaction is our top priority", "your health is our priority", "we strive to", "we pride ourselves", "state-of-the-art", "world-class", "second to none",
    "one-stop destination", "one-stop solution", "unleash", "elevate your", "take your .* to the next level", "don't miss out", "limited time only", "hurry",
    "we look forward to serving you", "we look forward to welcoming you", "feel free to reach out", "we value your feedback", "your feedback is valuable",
    "thank you for choosing us", "thanks for choosing us", "keep up the good work", "customer satisfaction is our", "we are committed to providing",
    "dedicated team of professionals", "highly qualified and experienced", "best in class", "best-in-class", "unparalleled", "cutting-edge",
    # Hindi / Hinglish boilerplate
    "aapki sewa mein hamesha", "aapki khushi hi hamari", "hamari sabse badi priority", "aapka feedback hamare liye bahut keemti", "hum aapki seva ke liye tatpar",
    "आपकी संतुष्टि हमारी प्राथमिकता", "आपकी सेवा में हमेशा", "आपका फीडबैक हमारे लिए बहुत",
]
_GENERIC_RE = [re.compile(p, re.I) for p in GENERIC_PHRASES]

PROMO_WORDS = re.compile(r"\b(book now|call now|visit us today|visit us now|order now|hurry|offer ends|limited (?:time|slots)|act now|don't miss|dont miss)\b", re.I)
STAR_WORDS = re.compile(r"\b(\d(?:\.\d)?\s*(?:/\s*5|stars?|star rating)|five[- ]star|four[- ]star|one[- ]star|5\s*stars?)\b", re.I)
EN_STOP = set("""a an and are as at be been but by can could did do does for from had has have he her his i if in into is it its me my not of on or our out she so
than that the their them then there these they this to too up us very was we were what when which who will with would you your yours about after all also any because
been before being both each get got just like more most much no now only other over really same some such than too via while""".split())
HINGLISH_MARKERS = set("""hai hain nahi nahin bahut accha acha achha bohot kaafi aur mera meri humne hum aap aapka aapki aapke ka ki ke ko se mein main tha thi bhi kya
ilaaj dhanyawad shukriya badhiya zabardast thik theek kaam karte karna kiya kiye lekin par toh to wala wali liye rahe raha rahi""".split())
APOLOGY = re.compile(r"\b(sorry|apolog|regret|disappoint|we hear you|understand|sincerely|upset|frustrat|dukh|khed|maafi|maaf)\w*|खेद|क्षमा|माफ़|माफी|दुख", re.I)
OFFLINE_INVITE = re.compile(r"\b(contact|reach|call|write|email|message|speak|talk|visit|connect|phone|dm)\b|संपर्क|बात|कॉल|बताइए|बताएं|sampark|baat|bataiye|batayein", re.I)


@dataclass
class Issue:
    code: str
    message: str
    retry: bool = False  # True = worth one regeneration with this message spelled out

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retry": self.retry}


@dataclass
class Assessment:
    issues: list[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def retry_reasons(self) -> list[str]:
        return [i.message for i in self.issues if i.retry]

    @property
    def score(self) -> float:
        """0 to 1: 1 minus a penalty per issue (retry-worthy issues weigh more)."""
        return max(0.0, round(1.0 - sum(0.25 if i.retry else 0.08 for i in self.issues), 3))


# ------------------------------------------------------------------ primitives
def words(text: str) -> list[str]:
    return [w.lower().strip("'") for w in WORD.findall(text or "")]


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if len(w) >= 4 and w not in EN_STOP and w not in HINGLISH_MARKERS]


def shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))} or ({tuple(w)} if w else set())


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of word 3-grams (0 = nothing shared, 1 = identical)."""
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def max_similarity(text: str, others: list[str]) -> float:
    return max((similarity(text, o) for o in others if o), default=0.0)


def opening(text: str, n: int = 4) -> str:
    return " ".join(words(text)[:n])


def generic_hits(text: str) -> list[str]:
    low = (text or "").lower()
    return [p.pattern for p in _GENERIC_RE if p.search(low)]


def script_ratio(text: str) -> float:
    """Share of letters that are Devanagari."""
    d, l = len(DEVANAGARI.findall(text or "")), len(LATIN.findall(text or ""))
    return d / (d + l) if d + l else 0.0


def hinglish_share(text: str) -> float:
    ws = words(text)
    return sum(1 for w in ws if w in HINGLISH_MARKERS) / len(ws) if ws else 0.0


def language_matches(text: str, lang: str) -> bool:
    if lang == "hi":
        return script_ratio(text) >= 0.6
    if lang == "hinglish":
        return script_ratio(text) < 0.1 and hinglish_share(text) >= 0.08
    return script_ratio(text) < 0.1 and hinglish_share(text) < 0.12  # English: Roman letters, not Hinglish


def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?।])\s+", (text or "").strip()) if s.strip()])


def specificity(text: str, source: str) -> tuple[int, list[str]]:
    """How many distinct content words of `source` (the review, the services) the text picks up, and which."""
    src = {w for w in content_words(source)}
    got = sorted({w for w in content_words(text) if w in src})
    return len(got), got


def _count(text: str, term: str) -> int:
    return len(re.findall(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", (text or "").lower()))


def stuffing(text: str, terms: list[str], *, max_distinct: int | None = 2) -> list[str]:
    """Search terms used more than once, and (when max_distinct is set) more than that many different terms in one text.
    A description may legitimately name several services, so it passes max_distinct=None and is only checked for repetition."""
    out = [t for t in terms if t and _count(text, t) > 1]
    if max_distinct is not None and sum(1 for t in terms if t and _count(text, t) >= 1) > max_distinct:
        out.append("more than two search terms in one text")
    return out


# ------------------------------------------------------------------ per-kind assessment
def assess_reply(text: str, *, rating: int, review_text: str = "", lang: str = "en", recent: list[str] | None = None, name: str | None = None) -> Assessment:
    a = Assessment()
    n = len(text or "")
    a.metrics = {"chars": n, "sentences": sentence_count(text), "generic": generic_hits(text), "recent_similarity": round(max_similarity(text, recent or []), 3)}
    if not language_matches(text, lang):
        a.issues.append(Issue("language", {"hi": "Write in Hindi using Devanagari script.", "hinglish": "Write in Hinglish (Hindi in Roman letters mixed with English), not Devanagari and not pure English.",
                                           "en": "Write in plain English, not Hindi or Hinglish."}[lang], True))
    if a.metrics["generic"]:
        a.issues.append(Issue("generic", "Avoid stock phrases (" + "; ".join(p.replace(".*", "...") for p in a.metrics["generic"][:3]) + "). Say it the way a person at the business would.", True))
    if n > 650 or a.metrics["sentences"] > 5:
        a.issues.append(Issue("too_long", "Too long. A reply is 2 to 4 short sentences.", True))
    if n < 25:
        a.issues.append(Issue("too_short", "Too short to feel personal.", True))
    if STAR_WORDS.search(text or ""):
        a.issues.append(Issue("mentions_rating", "Do not mention the star rating.", True))
    spec, hits = specificity(text, review_text)
    a.metrics["specific_terms"] = hits
    if len(content_words(review_text)) >= 6 and spec == 0:
        a.issues.append(Issue("not_specific", "It ignores what the reviewer actually wrote. Refer to at least one concrete detail from the review, in your own words.", True))
    if recent:
        if a.metrics["recent_similarity"] >= 0.45:
            a.issues.append(Issue("repeats_recent", "It is almost the same as a recent reply. Use different wording and structure.", True))
        elif sum(1 for r in recent if opening(r) == opening(text)) >= 2:
            a.issues.append(Issue("same_opening", "Replies keep starting the same way. Open differently.", True))
    if rating <= 2:
        if not APOLOGY.search(text or ""):
            a.issues.append(Issue("no_acknowledgement", "Acknowledge their experience sincerely before anything else.", True))
        if not OFFLINE_INVITE.search(text or ""):
            a.issues.append(Issue("no_contact_invite", "Invite them to contact the business directly to put it right.", False))
    if rating <= 3 and PROMO_WORDS.search(text or ""):
        a.issues.append(Issue("promotional", "No promotional wording in a reply to a critical review.", True))
    if len(EMOJI.findall(text or "")) > 1:
        a.issues.append(Issue("emoji", "At most one emoji.", False))
    return a


def assess_post(text: str, *, lang: str = "en", recent: list[str] | None = None, terms: list[str] | None = None, business: str = "", services: list[str] | None = None) -> Assessment:
    a = Assessment()
    n = len(text or "")
    a.metrics = {"chars": n, "sentences": sentence_count(text), "generic": generic_hits(text), "recent_similarity": round(max_similarity(text, recent or []), 3),
                 "opening": opening(text)}
    if not language_matches(text, lang):
        a.issues.append(Issue("language", {"hi": "Write in Hindi using Devanagari script.", "hinglish": "Write in Hinglish (Hindi in Roman letters mixed with English).", "en": "Write in plain English."}[lang], True))
    if a.metrics["generic"]:
        a.issues.append(Issue("generic", "Remove stock marketing phrases (" + "; ".join(p.replace(".*", "...") for p in a.metrics["generic"][:3]) + "). Say something specific and useful.", True))
    if recent:
        if a.metrics["recent_similarity"] >= 0.4:
            a.issues.append(Issue("repeats_recent", "Too similar to a recent post. Choose a different angle, not different words for the same idea.", True))
        elif sum(1 for r in recent if opening(r, 3) == opening(text, 3)) >= 1:
            a.issues.append(Issue("same_opening", "A recent post opened the same way. Start differently.", True))
    low_open = (text or "").strip().lower()
    if business and low_open.startswith((business.lower(), "welcome to " + business.lower(), "welcome to")):
        a.issues.append(Issue("opens_with_name", "Do not open with the business name or 'Welcome to'. Open with something the reader cares about.", True))
    if terms:
        s = stuffing(text, terms)
        if s:
            a.issues.append(Issue("keyword_stuffing", "Search terms are forced in (" + "; ".join(s[:2]) + "). Use at most two, once each, only where natural.", True))
    if HASHTAG.search(text or ""):
        a.issues.append(Issue("hashtags", "No hashtags in a Google post.", True))
    if len(EMOJI.findall(text or "")) > 1:
        a.issues.append(Issue("emoji", "At most one emoji.", False))
    if n and (n < 120 or a.metrics["sentences"] < 2):
        a.issues.append(Issue("thin", "Too thin: give the reader one concrete, useful thing.", False))
    if services:
        spec, hits = specificity(text, " ".join(services))
        a.metrics["service_terms"] = hits
    if text.count("!") > 2:
        a.issues.append(Issue("shouty", "Too many exclamation marks.", False))
    return a


def assess_description(text: str, *, lang: str = "en", business: str = "", terms: list[str] | None = None, services: list[str] | None = None) -> Assessment:
    a = Assessment()
    n = len(text or "")
    a.metrics = {"chars": n, "generic": generic_hits(text)}
    if not 400 <= n <= 750:
        a.issues.append(Issue("length", f"Aim for 400 to 750 characters (it is {n}).", True))
    if re.search(r"https?://|www\.|\+?\d[\d \-]{8,}\d", re.sub(r"\d{4}-\d{2}-\d{2}", "", text or "")):  # an ISO date is not a phone number
        a.issues.append(Issue("link_or_phone", "No links or phone numbers in a Google description.", True))
    if business and (text or "").lower().count(business.lower()) > 1:
        a.issues.append(Issue("repeats_name", "The business name appears more than once.", True))
    if a.metrics["generic"]:
        a.issues.append(Issue("generic", "Remove stock phrases (" + "; ".join(p.replace(".*", "...") for p in a.metrics["generic"][:3]) + ").", True))
    if terms:
        s = stuffing(text, terms, max_distinct=None)
        if s:
            a.issues.append(Issue("keyword_stuffing", "Search terms are forced in. Mention only what genuinely applies, naturally.", True))
    if not language_matches(text, lang):
        a.issues.append(Issue("language", "Wrong language or script for this business.", True))
    if services:
        spec, hits = specificity(text, " ".join(services))
        a.metrics["service_terms"] = hits
        if len(services) >= 2 and spec == 0 and script_ratio(text) < 0.5:  # Hindi text cannot be matched against English service names, so it is not judged here
            a.issues.append(Issue("not_specific", "It names none of the business's actual services.", True))
    if sum(1 for c in (text or "") if c.isupper()) > max(20, n * 0.2):
        a.issues.append(Issue("shouty", "Too many capital letters.", False))
    return a


def assess_review_draft(text: str, *, lang: str = "en", customer_input: str = "") -> Assessment:
    """The customer-facing review assistant: must stay close to what the customer said and read like a person, not an advert."""
    a = Assessment()
    a.metrics = {"chars": len(text or ""), "generic": generic_hits(text)}
    if not language_matches(text, lang):
        a.issues.append(Issue("language", "Wrong language or script.", True))
    if a.metrics["generic"]:
        a.issues.append(Issue("generic", "Sounds like an advert. Write like a customer.", True))
    if PROMO_WORDS.search(text or ""):
        a.issues.append(Issue("promotional", "Reviews are not advertisements.", True))
    if len(EMOJI.findall(text or "")) > 1 or HASHTAG.search(text or ""):
        a.issues.append(Issue("decorations", "No hashtags and at most one emoji.", False))
    # unsupported details: numbers and capitalised proper nouns that the customer never wrote
    src = (customer_input or "").lower()
    novel_nums = [m for m in re.findall(r"\d+", text or "") if m not in src]
    a.metrics["novel_numbers"] = novel_nums
    if novel_nums:
        a.issues.append(Issue("unsupported_numbers", "It states numbers the customer never gave: " + ", ".join(novel_nums[:3]) + ".", True))
    return a


def assess(kind: str, text: str, **kw) -> Assessment:
    return {"reply": assess_reply, "post": assess_post, "description": assess_description, "review_draft": assess_review_draft}[kind](text, **kw)
