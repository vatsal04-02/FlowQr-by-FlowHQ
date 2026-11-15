"""Deterministic scoring of one AI output against the case it was written for. No second model is involved: every number here can be recomputed
from the text and the case, so a score cannot be flattered by a lenient judge.

Metrics (each 0..1, higher is better; None when not applicable to the task):
  factual        no safety violation, no number/price the business never gave, no capitalised name the context never mentioned
  compliance     no health-claim, patient-confirmation, incentive or star-rating mention (health businesses are held to the strict list)
  relevance      replies: picks up a concrete detail from the review; posts/descriptions: names an actual service of the business
  naturalness    no stock phrases, not shouty, sentence lengths vary
  repetition     how different this output is from the others in the same batch (templates score low)
  language       written in the requested language and script
  brand_voice    respects the business's emoji / exclamation rules
  local          descriptions: names the city or area
  helpfulness    replies: the right move for the sentiment; posts/descriptions: a concrete tip/answer/next step
`quality_score` is services/ai/quality.assess (the same checks the product runs at generation time) and `composite` is the weighted mean of the above.

These are proxies for quality. They catch the failures that are visible without a person (made-up facts, boilerplate, wrong language, templating) and
cannot tell good writing from adequate writing. That is what the human review sheet (ai_eval/human.py) is for."""
from __future__ import annotations

import re

from app.services.agent.safety import _HEALTH_PATTERNS, check_text
from app.services.ai import quality
from app.ai_eval.dataset import Case, kb_for

METRIC_VERSION = 2  # v2 (2026-11-15): corrected after reading the first live run, see docs/AI_INTELLIGENCE.md "Metric corrections". Old and new outputs are always rescored with the same version.
WEIGHTS = {"factual": 0.25, "compliance": 0.15, "relevance": 0.15, "naturalness": 0.15, "repetition": 0.10, "language": 0.10, "brand_voice": 0.05, "helpfulness": 0.05}
INCENTIVE = re.compile(r"\b(discount|free|voucher|coupon|gift|reward|cashback|% off)\b", re.I)
THANKS = re.compile(r"\b(thank|thanks|grateful|glad|happy|pleased|delight\w*|appreciate|means a (?:lot|great deal)|to hear|so good to|made our day|touched|proud|wonderful|lovely|heartening)\w*|"
                    r"धन्यवाद|शुक्रिया|आभार|खुशी|अच्छा लगा|बहुत अच्छा|दिल खुश|dhanyawad|shukriya|khushi|khush|accha laga|achha laga|bahut accha|acha laga|sunkar|padh ?kar", re.I)
CAPITALISED = re.compile(r"(?<![.!?।]\s)(?<!^)\b([A-Z][a-z]{2,})\b")
GREETING_PREFIXES = ("hum", "aap", "hamar", "tum", "dear", "hello", "namaste", "sorry")  # Hinglish pronouns and greetings start sentences; they are not names


def _context_text(case: Case) -> str:
    b = case.business
    kb = kb_for(case.biz)
    parts = [b["name"], b["category"], b["city"], b["area"], b["description"], " ".join(b["services"]), b["hours"], b["audience"], b["voice"],
             " ".join(f"{o['name']} {o.get('details', '')}" for o in b["offers"]), " ".join(f"{f['q']} {f['a']}" for f in b["faqs"])]
    d = case.data
    parts += [d.get("text", ""), d.get("note", ""), " ".join(d.get("topics", [])), d.get("reviewer", ""), " ".join(d.get("recent", [])), d.get("current", "")]
    parts += [f"{o.get('price_inr', '')} {o.get('valid_until', '')}" for o in b["offers"]]  # a verified offer's price and end date are facts the text may state
    return " ".join(str(p) for p in parts if p)


KNOWN_WORDS = set("""monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october november december diwali holi navratri
dussehra eid christmas india indian google whatsapp gst sunday hindi english hinglish""".split())


def novel_entities(text: str, context: str) -> list[str]:
    ctx = context.lower()
    out = []
    for m in CAPITALISED.finditer(text):
        w = m.group(1)
        if w.lower() not in ctx and w.lower() not in KNOWN_WORDS and w.lower() not in quality.EN_STOP and w.lower() not in quality.HINGLISH_MARKERS and not w.lower().startswith(GREETING_PREFIXES):
            out.append(w)
    return sorted(set(out))


def novel_numbers(text: str, context: str) -> list[str]:
    clock = lambda t: re.sub(r"(\d{1,2}):\d{2}", r"\1", t)  # noqa: E731 - "9:00" and "9" are the same hour; minutes written as :00 are a format, not a new number
    allowed = set(re.findall(r"[0-9]+", clock(context)))
    return sorted({n for n in re.findall(r"[0-9]+", clock(text)) if n not in allowed and n.lstrip("0") not in {a.lstrip("0") for a in allowed}})


def score(case: Case, text: str, *, batch: list[str] | None = None) -> dict:
    """Metrics for one output. `batch` = the other outputs of the same task and model (for repetition)."""
    b = case.business
    kb = kb_for(case.biz)
    ctx = _context_text(case)
    lang = case.lang
    kind = {"reply": "reply", "post": "post", "description": "profile", "review_draft": "post"}[case.task]
    m: dict = {}

    violations = check_text(text, kb=kb, kind=kind) if case.task != "review_draft" else []
    nums, ents = novel_numbers(text, ctx), novel_entities(text, ctx)
    unsupported = len(violations) + len(nums) + len(ents)
    m["unsupported_claims"] = unsupported
    m["unsupported_detail"] = [v.code for v in violations] + [f"number {n}" for n in nums[:3]] + [f"name {e}" for e in ents[:3]]
    m["factual"] = 1.0 if unsupported == 0 else max(0.0, 1.0 - 0.34 * unsupported)

    comp = 1.0
    if b["health"]:
        hits = sum(1 for pat, _ in _HEALTH_PATTERNS for _m in [re.search(pat, text, re.I)] if _m)
        comp -= 0.5 * hits
    if case.task == "reply" and quality.STAR_WORDS.search(text):
        comp -= 0.5
    if case.task in ("reply", "post") and INCENTIVE.search(text) and not any(o["name"].split()[0].lower() in text.lower() for o in b["offers"]):
        comp -= 0.5
    m["compliance"] = max(0.0, comp)

    if case.task == "reply":
        spec, hits = quality.specificity(text, case.data["text"])
        want = case.data.get("must_reference") or []
        stem = lambda w: w.lower()[:4] if len(w) > 4 else w.lower()  # noqa: E731 - "waiting" counts as picking up "waited"
        got = [w for w in want if w.lower() in text.lower() or any(t.startswith(stem(w)) for t in quality.words(text))]
        m["relevance"] = 1.0 if not want else min(1.0, (len(got) / max(1, min(2, len(want)))) )
        m["referenced"] = got
    elif case.task in ("post", "description", "review_draft"):
        svc_hit, hits = quality.specificity(text, " ".join(b["services"]) + " " + b["category"])
        m["relevance"] = 1.0 if svc_hit >= 1 or (case.task == "review_draft" and quality.specificity(text, case.data.get("note", "") + " " + " ".join(case.data.get("topics", [])))[0] >= 1) else 0.0
        m["service_terms"] = hits

    gen = quality.generic_hits(text)
    sents = [len(s.split()) for s in re.split(r"(?<=[.!?।])\s+", text.strip()) if s.strip()]
    uniform = len(sents) >= 3 and (max(sents) - min(sents)) <= 2
    m["generic"] = gen
    m["naturalness"] = max(0.0, 1.0 - 0.34 * len(gen) - (0.15 if uniform else 0) - (0.2 if text.count("!") > 2 else 0))

    if batch:
        others = list(batch)
        if text in others:
            others.remove(text)  # this output itself, once; a second identical output in the batch is a real duplicate
        sims = [quality.similarity(text, o) for o in others if o]
        same_open = sum(1 for o in others if quality.opening(o, 3) == quality.opening(text, 3))
        m["repetition"] = max(0.0, 1.0 - max(sims, default=0.0) * 1.5 - 0.25 * min(same_open, 2))
    else:
        m["repetition"] = None

    m["language"] = 1.0 if quality.language_matches(text, lang) else 0.0

    emoji = len(quality.EMOJI.findall(text))
    m["brand_voice"] = 1.0 if (emoji <= (1 if b["emoji"] else 0) and text.count("!") <= 2) else 0.0

    m["local"] = (1.0 if (b["city"].lower() in text.lower() or b["area"].lower() in text.lower() or b["city"] in text) else 0.0) if case.task == "description" else None

    if case.task == "reply":
        r = case.data["rating"]
        if r <= 2:
            m["helpfulness"] = 1.0 if (quality.APOLOGY.search(text) and quality.OFFLINE_INVITE.search(text)) else 0.0
        elif r == 3:
            m["helpfulness"] = 1.0 if THANKS.search(text) or quality.APOLOGY.search(text) else 0.5
        else:
            m["helpfulness"] = 1.0 if THANKS.search(text) else 0.0
    elif case.task == "post":
        concrete = bool(re.search(r"\?|\b(tip|how|when|what|first|visit|call|book|bring|ask|try|timings?|open|from|every)\b", text, re.I)) or quality.script_ratio(text) > 0.5
        m["helpfulness"] = 1.0 if concrete and len(text) >= 120 else 0.5 if concrete else 0.0
    elif case.task == "description":
        m["helpfulness"] = 1.0 if 400 <= len(text) <= 750 and quality.specificity(text, " ".join(b["services"]))[0] >= 2 else 0.5 if 250 <= len(text) <= 750 else 0.0
    else:
        m["helpfulness"] = None

    if case.task == "reply":
        qa = quality.assess_reply(text, rating=case.data["rating"], review_text=case.data["text"], lang=lang)
    elif case.task == "post":
        qa = quality.assess_post(text, lang=lang, recent=case.data.get("recent"), business=b["name"], services=b["services"])
    elif case.task == "description":
        qa = quality.assess_description(text, lang=lang, business=b["name"], services=b["services"])
    else:
        qa = quality.assess_review_draft(text, lang=lang, customer_input=case.data.get("note", "") + " " + " ".join(case.data.get("topics", [])))
    m["quality_score"] = qa.score
    m["quality_issues"] = [i.code for i in qa.issues]
    m["clean"] = bool(unsupported == 0 and not qa.retry_reasons and m["language"] == 1.0 and m["compliance"] == 1.0)  # a proxy for "usable as is"

    num = sum(WEIGHTS[k] * m[k] for k in WEIGHTS if m.get(k) is not None)
    den = sum(WEIGHTS[k] for k in WEIGHTS if m.get(k) is not None)
    m["composite"] = round(num / den, 4) if den else 0.0
    return m
