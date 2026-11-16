"""The Business Intelligence layer: one tenant-isolated picture of a business, built from what is really known, for every AI task to use.

Sources (all read through the caller's session, so row-level security keeps it to one business):
  * the Business Knowledge Base the owner maintains (services, offers, FAQs, voice, approved/prohibited claims, audience, safety profile);
  * the live Google profile as last read (title, description, categories, hours, services), photos, posts, performance, Google's search terms;
  * the business's own reviews: rating mix and recurring themes customers raise, counted from the real text;
  * what has already been posted and replied, so new output can differ;
  * the place (city) and the season.

It never invents. If something is not known it is absent, and `missing_questions` says what to ask the owner. Review text is never put into a prompt
verbatim here: only theme counts, so a hostile review cannot smuggle instructions into another task's prompt.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GbpSnapshot, GoogleLocation, Location, ReplyDraft, ReplyStatus, Review, ScheduledPost, Tenant
from app.models.base import utcnow
from app.services.ai import craft

# Recurring topics in reviews. English and common Hinglish spellings. Counted per review (a review mentioning a topic twice counts once).
THEMES: dict[str, tuple[str, re.Pattern]] = {
    "waiting time": ("wait", re.compile(r"\b(wait(ed|ing)?|waiting time|long queue|queue|late|delay(ed)?|on time|punctual|prompt|intezaar|der se|jaldi)\b", re.I)),
    "staff behaviour": ("staff", re.compile(r"\b(staff|team|behaviou?r|polite|rude|friendly|helpful|courteous|nurse|receptionist|attend(ed|ant)|misbehav\w*|vyavhar)\b", re.I)),
    "cleanliness": ("clean", re.compile(r"\b(clean|hygien\w*|dirty|neat|sanitis\w*|sanitiz\w*|safai|saaf)\b", re.I)),
    "price and value": ("price", re.compile(r"\b(price|prices|pricing|cost|costly|expensive|cheap|affordable|value for money|reasonable|fees?|charges?|paisa|mehenga|sasta)\b", re.I)),
    "expertise and explanation": ("expert", re.compile(r"\b(expert|experienced|knowledgeable|explain(ed|s)?|guid(ed|ance)|advice|diagnos\w*|treatment|doctor|therapist|trainer|stylist|chef|teacher|samjhaya|ilaaj)\b", re.I)),
    "results and quality": ("quality", re.compile(r"\b(result|results|quality|taste|tasty|delicious|fresh|improv\w*|recover\w*|relief|better|best|amazing|excellent|perfect|zabardast|badhiya|mast)\b", re.I)),
    "ambience and comfort": ("ambience", re.compile(r"\b(ambience|ambiance|atmosphere|comfortable|comfort|decor|music|spacious|crowded|noisy|peaceful|seating|parking)\b", re.I)),
    "booking and timings": ("booking", re.compile(r"\b(appointment|booking|booked|slot|timings?|open|closed|call|phone|response|reply|replied|available)\b", re.I)),
}
THEME_LABEL = {k: v[0] for k, v in THEMES.items()}


def review_themes(reviews: list[tuple[int, str]]) -> dict:
    """[(rating, text)] -> {"praise": [(theme, n)], "concerns": [(theme, n)], "n": int, "avg": float, "mix": {1..5: n}}.
    Praise = themes in 4-5 star reviews, concerns = themes in 1-3 star reviews. A heuristic from word lists: it counts topics, it does not read minds."""
    praise: dict[str, int] = {}
    concerns: dict[str, int] = {}
    mix = {i: 0 for i in range(1, 6)}
    total = 0
    for rating, text in reviews:
        mix[max(1, min(5, int(rating)))] += 1
        total += rating
        for theme, (_, pat) in THEMES.items():
            if text and pat.search(text):
                (praise if rating >= 4 else concerns)[theme] = (praise if rating >= 4 else concerns).get(theme, 0) + 1
    rank = lambda d: sorted(d.items(), key=lambda kv: -kv[1])  # noqa: E731
    return {"n": len(reviews), "avg": round(total / len(reviews), 2) if reviews else None, "mix": mix, "praise": rank(praise)[:4], "concerns": rank(concerns)[:4]}


def _pct(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100)


def performance_trend(perf: dict | None) -> dict | None:
    """From the snapshot's two 28-day windows: {"customer actions": {current, previous, change_pct}} (calls + website clicks + directions, summed by the snapshot).
    None when Google returned no performance data. Never estimated."""
    if not perf or "current" not in perf:
        return None
    cur, prev = perf.get("current"), perf.get("previous")
    if isinstance(cur, dict):  # per-metric shape
        return {m: {"current": c, "previous": (prev or {}).get(m), "change_pct": _pct(c, (prev or {}).get(m)) if (prev or {}).get(m) is not None else None}
                for m, c in cur.items() if c is not None} or None
    if cur is None:
        return None
    return {"customer actions": {"current": cur, "previous": prev, "change_pct": _pct(cur, prev) if prev is not None else None}}


def build(db: Session, tenant: Tenant, kb: dict, *, google_location_id: uuid.UUID | None = None, today: date | None = None) -> dict:
    """Everything known about this business for one location (or the first selected one). Safe to call without Google connected."""
    today = today or utcnow().date()
    gl = db.get(GoogleLocation, google_location_id) if google_location_id else db.scalar(
        select(GoogleLocation).where(GoogleLocation.tenant_id == tenant.id, GoogleLocation.selected.is_(True)).order_by(GoogleLocation.created_at))
    loc = db.get(Location, gl.location_id) if gl and gl.location_id else db.scalar(select(Location).where(Location.tenant_id == tenant.id).order_by(Location.created_at))
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gl.id)) if gl else None
    info = (snap.info if snap else None) or {}

    q = select(Review.rating, Review.text).where(Review.tenant_id == tenant.id).order_by(Review.review_created_at.desc()).limit(80)
    if gl:
        q = q.where(Review.google_location_id == gl.id)
    themes = review_themes([(r, t or "") for r, t in db.execute(q).all()])
    unanswered = db.scalar(select(func.count()).select_from(Review).where(Review.tenant_id == tenant.id, Review.google_reply_text.is_(None),
                                                                           *( [Review.google_location_id == gl.id] if gl else []))) or 0

    posts_q = select(ScheduledPost.summary).where(ScheduledPost.tenant_id == tenant.id, ScheduledPost.status != "canceled").order_by(ScheduledPost.created_at.desc()).limit(8)
    if gl:
        posts_q = posts_q.where(ScheduledPost.google_location_id == gl.id)
    own_posts = [s for (s,) in db.execute(posts_q).all()]
    google_posts = [p.get("summary") or "" for p in (snap.posts if snap and snap.posts else [])][:8]
    recent_posts = list(dict.fromkeys([p for p in own_posts + google_posts if p]))[:8]

    replies = [b for (b,) in db.execute(select(ReplyDraft.body).where(ReplyDraft.tenant_id == tenant.id, ReplyDraft.status.in_((ReplyStatus.published, ReplyStatus.approved)))
                                          .order_by(ReplyDraft.created_at.desc()).limit(8)).all()]
    media = {}
    for m in (snap.media if snap and snap.media else []):
        media[m.get("category") or "OTHER"] = media.get(m.get("category") or "OTHER", 0) + 1
    perf = (snap.performance if snap else None) or {}
    terms = [k["keyword"] for k in (perf.get("keywords") or []) if k.get("keyword") and k.get("value")][:10]

    intel = {
        "business": tenant.name, "category": tenant.category, "city": (loc.city if loc else None) or "", "area": (loc.address_line if loc else None) or "",
        "language": tenant.language or "en", "audience": kb.get("audience") or "", "safety_profile": kb.get("safety_profile"),
        "profile": {"description": (info.get("description") or "").strip(), "primary_category": (info.get("primary_category") or {}).get("name"),
                    "additional_categories": [c.get("name") for c in (info.get("additional_categories") or []) if c.get("name")],
                    "services_on_google": [s if isinstance(s, str) else s.get("name") for s in (info.get("services") or [])], "has_hours": bool(info.get("hours")),
                    "known": bool(info)},
        "reviews": {**themes, "unanswered": unanswered}, "recent_posts": recent_posts,
        "recent_post_types": [craft.classify_post(p) for p in recent_posts], "recent_replies": replies,
        "photos": {"total": sum(media.values()), "by_category": media} if snap and snap.media is not None else None,
        "performance": performance_trend(perf), "search_terms": terms, "occasions": craft.occasions(today), "today": today.isoformat(),
    }
    intel["missing"] = missing_questions(kb, intel)
    return intel


def missing_questions(kb: dict, intel: dict) -> list[dict]:
    """What to ask the owner, in the order that most improves output. Only things the AI cannot get elsewhere."""
    out = []

    def ask(key, question, why):
        out.append({"key": key, "question": question, "why": why})

    if not (kb.get("description") or "").strip() and not intel["profile"]["description"]:
        ask("description", "In two or three sentences, what does your business do and for whom?", "Without it the AI can only write generic text.")
    if not kb.get("services"):
        ask("services", "Which services or products should customers know about?", "Posts and descriptions can only mention what you list.")
    if not (kb.get("brand_voice") or "").strip():
        ask("brand_voice", "How do you want to sound: warm, formal, playful, plain?", "It keeps replies and posts sounding like you.")
    if not (kb.get("audience") or "").strip():
        ask("audience", "Who are your best customers (for example: office workers nearby, parents of school children)?", "It decides which tips and examples are relevant.")
    if not (kb.get("hours") or "").strip() and not intel["profile"]["has_hours"]:
        ask("hours", "What are your opening hours?", "Customers ask; replies and posts can point to them.")
    if len(kb.get("faqs") or []) < 3:
        ask("faqs", "What three questions do customers ask you most, and what do you answer?", "Each becomes a useful, accurate post.")
    if not intel["city"]:
        ask("city", "Which city or area do you serve?", "Local relevance needs a place.")
    return out


def render(intel: dict, *, include: tuple[str, ...] = ("place", "audience", "reviews", "posts", "photos", "performance", "season", "terms")) -> str:
    """Prompt block of observed facts. Complements services/agent/knowledge.render (the owner's facts); every line says where it came from."""
    L = ["WHAT WE OBSERVE ABOUT THIS BUSINESS (measured, not claims you may make):"]
    if "place" in include and intel.get("city"):
        L.append(f"- Location: {intel['area'] + ', ' if intel.get('area') else ''}{intel['city']}")
    if "audience" in include and intel.get("audience"):
        L.append(f"- Customers the owner wants to reach: {intel['audience']}")
    rv = intel.get("reviews") or {}
    if "reviews" in include and rv.get("n"):
        L.append(f"- From {rv['n']} real reviews (average {rv['avg']}): customers most often praise " + (", ".join(f"{t} ({c})" for t, c in rv["praise"]) or "nothing specific yet")
                 + ("; concerns raised: " + ", ".join(f"{t} ({c})" for t, c in rv["concerns"]) if rv["concerns"] else ""))
    if "posts" in include and intel.get("recent_posts"):
        L.append("- Recent posts (do NOT repeat their topic, angle or opening):")
        L += [f"    * {p[:150]}" for p in intel["recent_posts"][:5]]
        types = intel.get("recent_post_types") or []
        if types:
            L.append("  Recent post types: " + ", ".join(types[:5]) + ". Choose a different type.")
    if "photos" in include and intel.get("photos") is not None:
        ph = intel["photos"]
        L.append(f"- Photos on the Google profile: {ph['total']} (" + (", ".join(f"{k.lower()} {v}" for k, v in ph["by_category"].items()) or "none") + ")")
    if "performance" in include and intel.get("performance"):
        L.append("- Last 28 days vs the 28 before (Google): " + ", ".join(f"{m.lower().replace('_', ' ')} {v['current']}" + (f" ({v['change_pct']:+d}%)" if v["change_pct"] is not None else "") for m, v in list(intel["performance"].items())[:5]))
    if "terms" in include and intel.get("search_terms"):
        L.append("- Search terms people used to find this profile (reported by Google): " + ", ".join(intel["search_terms"][:8]))
    if "season" in include and intel.get("occasions"):
        L.append("- Around now (general, not a claim about the business): " + "; ".join(intel["occasions"][:3]))
    return "\n".join(L) if len(L) > 1 else ""
