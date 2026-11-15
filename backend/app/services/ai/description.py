"""Google Business Profile 'About' description writer: factual, readable, specific, grounded in the knowledge base and what Google reports.

The old one-line prompt produced the same brochure paragraph for everyone. This one tells the model what a good description does (who you serve, what
you do, what a visit is like, where, how to reach you), gives it the business's own facts and what customers actually praise, and checks the result
for length, stock phrases, keyword stuffing, invented specifics and language. Search terms are context for relevance, never a list to insert."""
from __future__ import annotations

from app.models import Tenant
from app.services.agent import knowledge as kbs
from app.services.agent.safety import check_text
from app.services.ai import craft, intelligence, quality
from app.services.ai.base import AIUnavailable, LLMProvider

SYSTEM = """You write the 'About' description of a Google Business Profile for a local business in India. A customer deciding whether to visit reads it in ten seconds.

A GOOD DESCRIPTION
- Opens with what the business is and who it serves, in the customer's words, not a slogan.
- Names the real services, in plain words, using the terms customers actually search for where they truly apply (once each, naturally).
- Says one thing that helps a customer decide: how a visit works, who the service suits, what to bring or expect, or the business's approach as the owner describes it.
- Mentions the area it serves, if given. Ends with how to get started in plain words, without a phone number or link (Google rejects them).
- 450 to 700 characters, 3 to 5 sentences, flowing prose. No lists, no all-caps, no emoji.

NEVER
- State anything not in the BUSINESS FACTS: no invented services, prices, offers, years in business, awards, certifications, staff, results or timings.
- Promise outcomes, make comparative claims ("best", "leading", "number 1") or use stock phrases ("state-of-the-art", "one-stop", "your satisfaction is our priority").
- Repeat the business name more than once, stuff keywords, or write the search terms as a list.

OUTPUT: only the description text."""


def build_prompt(tenant: Tenant, kb: dict, intel: dict | None, terms_line: str | None, lang: str) -> str:
    pb = craft.playbook(kb.get("category") or tenant.category)
    parts = [kbs.render(kb)]
    if intel:
        obs = intelligence.render(intel, include=("place", "audience", "reviews", "terms"))
        if obs:
            parts.append(obs)
        cur = (intel.get("profile") or {}).get("description")
        if cur:
            parts.append("The current description on Google (improve on it, keep what is accurate and specific, drop what is generic):\n" + cur[:750])
    if terms_line and not (intel and intel.get("search_terms")):
        parts.append(terms_line)
    parts.append(f"What customers of this kind of business look for: {pb['care']}.")
    parts.append(f"LANGUAGE: {craft.LANGUAGE_STYLE.get(lang, craft.LANGUAGE_STYLE['en'])}")
    parts.append("Write the description.")
    return "\n\n".join(parts)


def draft_description(provider: LLMProvider, tenant: Tenant, kb: dict, intel: dict | None = None, *, terms_line: str | None = None, language: str | None = None):
    """(text, quality.Assessment). Safety failure twice -> AIUnavailable(code="rejected"). Quality problems get one retry, then only lower the score."""
    lang = language or tenant.language or "en"
    if lang not in craft.LANGUAGE_STYLE:
        lang = "en"
    user = build_prompt(tenant, kb, intel, terms_line, lang)
    terms = list((intel or {}).get("search_terms") or [])
    services = list(kb.get("services") or [])

    def judge(out: str):
        bad = check_text(out, kb=kb, kind="profile") if out else []
        qa = quality.assess_description(out, lang=lang, business=tenant.name, terms=terms, services=services) if out else None
        return bad, qa

    clean = lambda s: s.strip().strip('"').strip()  # noqa: E731
    out = clean(provider.generate(SYSTEM, user, max_tokens=500, temperature=0.6))
    bad, qa = judge(out)
    if bad or (qa and qa.retry_reasons):
        first, first_qa = out, qa
        why = [b.message for b in bad] + (qa.retry_reasons if qa else [])
        out = clean(provider.generate(SYSTEM, user + "\n\nYour previous draft was rejected because: " + " ".join(why) + "\nWrite a new description that fixes all of this.", max_tokens=500, temperature=0.4))
        bad, qa = judge(out)
        if bad:
            raise AIUnavailable("The description broke a safety rule twice, so it was not shown", code="rejected")
        if first_qa is not None and qa is not None and first_qa.score > qa.score and not judge(first)[0]:
            out, qa = first, first_qa
    if len(out) < 60:
        raise AIUnavailable("The description was too short, so it was not shown", code="rejected")
    return out[:750], qa
