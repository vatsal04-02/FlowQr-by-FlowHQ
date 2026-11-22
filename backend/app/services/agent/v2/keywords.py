"""Local search opportunity discovery. PURE.

Builds candidate local searches ("physiotherapy in Gomti Nagar") from facts the business verifiably has: the services the owner listed, the business type, the places it is in or serves,
the search terms Google itself reports people found it with, and what customers actually talk about in reviews. Ranks them by business relevance, search intent, geography, how little the
profile already covers them and how much real evidence supports them.

What it does NOT do, on purpose: it invents no search volume, difficulty or "expected traffic"; it does not treat a Places result position as the exact Google Maps rank; and it never adds a
term for a service or a place the business does not have. A term is a SUGGESTION TO TRACK that the owner accepts, never something written into the profile by this module."""
from __future__ import annotations

import re

from app.services.agent.v2.fields import key_of, norm

MAX_RESULTS = 12
INTENTS = (("{service} in {place}", 1.0, "looking to use the service in that area"), ("{service} near me", 0.8, "looking for the closest option"))


def localities_from_address(address: str | None, service_area_names: list[str] | None = None) -> list[str]:
    """Place names from an address, most specific first: "12 MG Road, Gomti Nagar, Lucknow 226010" -> ["Gomti Nagar", "Lucknow"]. Segments with digits (house numbers, pin codes) are dropped."""
    out: list[str] = []
    for part in reversed([norm(re.sub(r"\s+\d{5,6}$", "", norm(p))) for p in re.split(r"[,\n]", address or "")]):  # a trailing pin code is dropped, the place name before it is kept
        if not part or re.search(r"\d", part) or len(part) < 3 or key_of(part) in {key_of(o) for o in out}:
            continue
        out.append(part)
    out = out[:3]
    for n in service_area_names or []:
        n = norm(n).split(",")[0]
        if n and key_of(n) not in {key_of(o) for o in out}:
            out.append(n)
    return list(reversed(out))[:5]


def _covered(term: str, text: str) -> bool:
    toks = [t for t in key_of(term).split() if t not in {"in", "near", "me", "the", "a"}]
    hay = key_of(text)
    return bool(toks) and all(t in hay for t in toks)


def discover(*, services: list[str], category: str | None, localities: list[str], google_terms: list[dict] | None, tracked: list[str], description: str | None,
             review_topics: list[str] | None = None, limit: int = MAX_RESULTS) -> list[dict]:
    tracked_keys = {key_of(t) for t in tracked}
    review_keys = {key_of(t) for t in review_topics or []}
    out: dict[str, dict] = {}

    def add(term: str, relevance: float, intent: float, geo: float, source: str, evidence: list[str]):
        k = key_of(term)
        if not k or k in tracked_keys:
            return
        covered = _covered(term, description or "")
        gap = 0.4 if covered else 1.0
        bonus = min(0.1, 0.05 * len(evidence))
        score = round(0.4 * relevance + 0.2 * intent + 0.2 * geo + 0.2 * gap + bonus, 3)
        cur = out.get(k)
        if cur is None or score > cur["score"]:
            out[k] = {"term": norm(term), "score": score, "source": source, "evidence": evidence, "in_description": covered,
                      "components": {"relevance": relevance, "intent": intent, "geography": geo, "gap": gap}}

    places = list(reversed(localities))  # most specific first
    google_hits = [t for t in (google_terms or []) if t.get("keyword")]
    svc = [norm(s if isinstance(s, str) else (s.get("name") if isinstance(s, dict) else "")) for s in services]
    for s in [x for x in svc if x]:
        ev = [f"you list \"{s}\" as a service"]
        if any(key_of(s) in key_of(g["keyword"]) for g in google_hits):
            ev.append("Google reports people finding you with a search that includes it")
        if any(key_of(s) in r or r in key_of(s) for r in review_keys if r):
            ev.append("customers mention it in reviews")
        for i, place in enumerate(places):
            geo = 1.0 if i == 0 else 0.85
            for tmpl, intent, _ in INTENTS[:1]:
                add(tmpl.format(service=s, place=place), 1.0, intent, geo, "verified_service", ev + [f"you are in or serve {place}"])
        add(INTENTS[1][0].format(service=s), 1.0, INTENTS[1][1], 0.7, "verified_service", ev)
    if category:
        for i, place in enumerate(places):
            add(f"{norm(category)} in {place}", 0.8, 1.0, 1.0 if i == 0 else 0.85, "business_type", [f"your business type is \"{norm(category)}\"", f"you are in or serve {place}"])
        add(f"{norm(category)} near me", 0.8, 0.8, 0.7, "business_type", [f"your business type is \"{norm(category)}\""])
    # what Google itself says people searched, and that is not tracked yet: real data, shown as Google gave it
    for g in google_hits:
        kw = norm(g["keyword"])
        if g.get("value") is not None:
            shown = f"Google reports about {g['value']} impressions from this search in the last months"
        else:
            shown = f"Google reports fewer than {g.get('below')} impressions (it does not give exact small numbers)" if g.get("below") else "Google reports this search"
        add(kw, 0.9, 0.9, 0.8, "google_search_terms", [shown])
    ranked = sorted(out.values(), key=lambda x: (-x["score"], x["term"]))
    # Google's own reported searches are real demand evidence: they keep a few guaranteed places so generated combinations cannot crowd them out
    reserved = [o for o in ranked if o["source"] == "google_search_terms"][:max(0, min(4, limit // 3))]
    top = [o for o in ranked if o not in reserved][:max(0, limit - len(reserved))]
    return sorted(top + reserved, key=lambda x: (-x["score"], x["term"]))
