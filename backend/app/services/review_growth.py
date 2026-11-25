"""Review Growth domain logic: identifiers, review-URL resolution, funnel events, analytics, retention."""
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlparse

from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AIGenerationLog, GoogleLocation, Location, RetiredCampaignId, ReviewCampaign, ReviewEvent, ReviewSession, Tenant
from app.models.base import utcnow
from app.services import cards as cards_svc
from app.services.review_suggestions import CATALOG, all_topics, resolve_category, topics_for

# Funnel stages. Each is recorded at most once per customer session, so rates between stages never exceed 100%.
FUNNEL = (
    ("scans", "scan", "Page opened"),
    ("feedback_submitted", "feedback_submitted", "Started a review"),  # asked for AI help OR chose to write it themselves
    ("drafts_approved", "draft_approved", "Confirmed their review"),
    ("google_redirects", "google_redirect", "Continued to Google"),
)
# Not funnel steps (a customer takes one path or the other), but counted per campaign and in the "writing path" breakdown.
EXTRA_STATS = (
    ("ai_requested", "ai_requested"), ("manual_selected", "manual_selected"), ("drafts_generated", "draft_generated"),
)
SESSION_VALID_HOURS = 24


def new_public_id() -> str:
    return secrets.token_urlsafe(16)  # 128 bits from the OS CSPRNG, 22 URL-safe chars


def issue_public_id(db: Session) -> str:
    """A public id no campaign has now or ever had (retired ids are remembered and never reissued)."""
    while True:
        candidate = new_public_id()
        if (not db.scalar(select(ReviewCampaign.id).where(ReviewCampaign.public_id == candidate))
                and not db.scalar(select(RetiredCampaignId.id).where(RetiredCampaignId.public_id == candidate))):
            return candidate


def new_session_identifier() -> str:
    return secrets.token_urlsafe(16)


def review_url_kind(url: str | None) -> str:
    """"direct" when the link opens Google's Write-a-review box ("g.page/r/<id>/review", "search.google.com/local/writereview?placeid=...",
    ".../review" paths), "listing" when it is the business's general Maps/Search listing (the customer would have to find the review button
    themselves), "unknown" for short links (maps.app.goo.gl, goo.gl) that could be either, "none" when empty."""
    if not url:
        return "none"
    try:
        p = urlparse(url.strip())
    except ValueError:
        return "unknown"
    host, path, query = (p.hostname or "").lower(), p.path.lower(), p.query.lower()
    if "writereview" in path or "writereview" in query or "action=write" in query:
        return "direct"
    if host.endswith("g.page") or host == "g.co":
        return "direct" if re.search(r"/r/[^/]+/review/?$", path) else "listing"
    if host in ("maps.app.goo.gl", "goo.gl", "page.link") or host.endswith(".page.link"):
        return "unknown"
    if host.endswith("google.com") or host.endswith("google.co.in"):
        if path.endswith("/review") or (path.endswith("/reviews") and "placeid" in query):
            return "direct"
        return "listing"  # /maps/place/..., /maps?cid=..., search results
    return "unknown"


def resolve_review_url(db: Session, location: Location) -> tuple[str | None, str | None]:
    """(url, source). The location's own link wins (manual, or already copied from Google) UNLESS it is only the general listing and the mapped
    Business Profile gives us the place id: then the direct Write-a-review link is used, so the customer lands in the review box, not on a
    page they must search for the review button. No second OAuth flow and no extra Google calls."""
    if location.review_url:
        if review_url_kind(location.review_url) == "listing":
            direct, source = google_review_url(db, location)
            if direct:
                return direct, source
        return location.review_url, location.review_url_source
    return google_review_url(db, location)


def google_review_url(db: Session, location: Location) -> tuple[str | None, str | None]:
    gl = db.scalar(select(GoogleLocation).where(GoogleLocation.location_id == location.id, GoogleLocation.tenant_id == location.tenant_id)
                   .order_by(GoogleLocation.selected.desc(), GoogleLocation.created_at))
    if gl and gl.review_url:
        return gl.review_url, "google"
    if gl and gl.place_id:
        return f"https://search.google.com/local/writereview?placeid={quote(gl.place_id, safe='')}", "google"
    return None, None


def record_event(db: Session, campaign: ReviewCampaign, event_type: str, *, ip: str, ua: str | None,
                 session: ReviewSession | None = None, suggestion_id: str | None = None, rating: int | None = None) -> ReviewEvent:
    ev = ReviewEvent(
        tenant_id=campaign.tenant_id, campaign_id=campaign.id, session_id=session.id if session else None, location_id=campaign.location_id,
        event_type=event_type, suggestion_id=suggestion_id, rating=rating, visitor_hash=cards_svc.visitor_hash(ip, ua), is_bot=cards_svc.is_bot(ua), created_at=utcnow(),
    )
    db.add(ev)
    return ev


def campaign_stats(db: Session, campaign_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """All-time per-campaign counts for the list view (bots excluded)."""
    out: dict[uuid.UUID, dict[str, int]] = {cid: {} for cid in campaign_ids}
    if not campaign_ids:
        return out
    by_type = {et: key for key, et, _ in FUNNEL} | {et: key for key, et in EXTRA_STATS}
    rows = db.execute(select(ReviewEvent.campaign_id, ReviewEvent.event_type, func.count()).where(
        ReviewEvent.campaign_id.in_(campaign_ids), ReviewEvent.is_bot.is_(False)).group_by(ReviewEvent.campaign_id, ReviewEvent.event_type)).all()
    for cid, et, n in rows:
        if et in by_type:
            out[cid][by_type[et]] = n
    uniq = db.execute(select(ReviewEvent.campaign_id, func.count(func.distinct(ReviewEvent.visitor_hash))).where(
        ReviewEvent.campaign_id.in_(campaign_ids), ReviewEvent.is_bot.is_(False), ReviewEvent.event_type == "scan").group_by(ReviewEvent.campaign_id)).all()
    for cid, n in uniq:
        out[cid]["unique_scans"] = n  # distinct devices per day (the visitor hash is salted daily and cannot be reversed)
    return out


def purge_expired(db: Session, *, now: datetime | None = None, days: int | None = None) -> int:
    """Delete customer answers and drafts older than the retention period. Events keep their counts (no text); drafts
    cascade with their session. Returns the number of sessions removed."""
    cutoff = (now or utcnow()) - timedelta(days=days if days is not None else settings.review_session_retention_days)
    res = db.execute(delete(ReviewSession).where(ReviewSession.created_at < cutoff))
    db.commit()
    return res.rowcount or 0


def topic_popularity(db: Session, ev, tenant: Tenant | None) -> tuple[list[dict], int]:
    """Which topic chips customers pick, most popular first, plus how many distinct customers picked at least one. Topic ids only: no text."""
    rows = db.execute(select(ev.c.suggestion_id, func.count(), func.count(func.distinct(ev.c.session_id))).where(
        ev.c.event_type == "suggestion_selected", ev.c.suggestion_id.is_not(None)).group_by(ev.c.suggestion_id)).all()
    sessions = db.scalar(select(func.count(func.distinct(ev.c.session_id))).where(ev.c.event_type == "suggestion_selected")) or 0
    labels = {t.id: t.en for entry in CATALOG.values() for t in entry["topics"]}
    if tenant is not None:  # this business's own wording wins where ids are shared between categories
        key = resolve_category(tenant.category, (tenant.review_context or {}).get("category_key"))
        labels.update({t.id: t.en for t in topics_for(key)})
        labels.update({t.id: t.en for t in all_topics(tenant.review_context, key)})  # and the business's own service chips
    out = [{"id": sid, "label": labels.get(sid, sid.replace("_", " ").capitalize()), "count": n} for sid, n, _ in rows]
    out.sort(key=lambda r: (-r["count"], r["label"]))
    return out, sessions


def rating_distribution(db: Session, ev) -> dict:
    """How customers rated their visit ON THE FLOWQR PAGE (1-5), from `feedback_submitted` events. This is NOT the business's Google rating: Google
    ratings are chosen by customers on Google, after they leave, and are shown under Reviews. Counts only; no text."""
    rows = dict(db.execute(select(ev.c.rating, func.count()).where(ev.c.event_type == "feedback_submitted", ev.c.rating.is_not(None)).group_by(ev.c.rating)).all())
    unrated = db.scalar(select(func.count()).where(ev.c.event_type == "feedback_submitted", ev.c.rating.is_(None))) or 0
    dist = {str(i): int(rows.get(i, 0)) for i in range(1, 6)}
    rated = sum(dist.values())
    return {"distribution": dist, "rated": rated, "unrated": int(unrated), "average": round(sum(int(k) * v for k, v in dist.items()) / rated, 2) if rated else None,
            "source": "Chosen by customers on your FlowQR review page. Not your Google rating."}


def ai_quality(db: Session, tenant_id: uuid.UUID, lo: datetime, hi: datetime) -> dict:
    """Cost and quality of customer draft generation in the period (admin test runs excluded). Figures come from the provider's own usage
    reports and our logs; `cost_per_accepted_draft_usd` is only given when the provider reported a cost."""
    a = AIGenerationLog
    r = db.execute(select(
        func.count(), func.count().filter(a.status == "ok"), func.count().filter(a.status == "rejected"), func.count().filter(a.status == "error"),
        func.coalesce(func.sum(a.prompt_tokens), 0), func.coalesce(func.sum(a.completion_tokens), 0), func.coalesce(func.sum(a.model_calls), 0),
        func.coalesce(func.sum(a.attempts), 0), func.coalesce(func.sum(func.greatest(a.attempts - 1, 0)), 0),
        func.coalesce(func.sum(a.rejects_rules), 0), func.coalesce(func.sum(a.rejects_factcheck), 0), func.coalesce(func.sum(a.cost_usd), 0),
        func.avg(a.latency_ms).filter(a.status == "ok"), func.percentile_cont(0.5).within_group(a.latency_ms).filter(a.status == "ok"),
        func.count().filter(a.cost_usd.is_not(None)),
    ).where(a.tenant_id == tenant_id, a.kind == "review_generate", a.created_at >= lo, a.created_at < hi)).one()
    (n, ok, rejected, errored, tin, tout, calls, attempts, retries, rej_rules, rej_fc, cost, lat_avg, lat_p50, costed) = r
    factchecks = max(int(calls) - int(attempts), 0)  # every model call that was not a write was a fact-check
    cost = float(cost or 0)
    return {
        "requests": n, "accepted": ok, "rejected": rejected, "failed": errored, "model_calls": int(calls), "write_attempts": int(attempts), "retries": int(retries),
        "tokens_in": int(tin), "tokens_out": int(tout), "cost_usd": round(cost, 6) if costed else None,
        "cost_per_accepted_draft_usd": round(cost / ok, 6) if ok and costed else None,
        "avg_calls_per_request": round(int(calls) / n, 2) if n else None,
        "rules_rejection_rate": _rate(int(rej_rules), int(attempts)), "factcheck_rejection_rate": _rate(int(rej_fc), factchecks),
        "latency_ms_avg": int(lat_avg) if lat_avg is not None else None, "latency_ms_median": int(lat_p50) if lat_p50 is not None else None,
    }


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def analytics(db: Session, *, tenant_id: uuid.UUID, tz: str, start: date, end: date, lo: datetime, hi: datetime,
              campaign_id: uuid.UUID | None, fill, campaign_ids: list[uuid.UUID] | None = None, location_id: uuid.UUID | None = None) -> dict:
    """`campaign_ids`: when not None, the ONLY campaigns the caller may see (location-restricted staff)."""
    ev_q = select(ReviewEvent).where(ReviewEvent.tenant_id == tenant_id, ReviewEvent.is_bot.is_(False),
                                     ReviewEvent.created_at >= lo, ReviewEvent.created_at < hi)
    if campaign_id:
        ev_q = ev_q.where(ReviewEvent.campaign_id == campaign_id)
    if campaign_ids is not None:
        ev_q = ev_q.where(ReviewEvent.campaign_id.in_(campaign_ids))
    if location_id:  # by where the campaign pointed when the event happened
        ev_q = ev_q.where(ReviewEvent.location_id == location_id)
    ev = ev_q.subquery()

    totals = dict(db.execute(select(ev.c.event_type, func.count()).group_by(ev.c.event_type)).all())
    unique_visitors = db.scalar(select(func.count(func.distinct(ev.c.visitor_hash))).where(ev.c.event_type == "scan")) or 0

    funnel, prev = [], None
    first = totals.get("scan", 0)
    for key, et, label in FUNNEL:
        n = totals.get(et, 0)
        funnel.append({"key": key, "label": label, "count": n,
                       "rate_of_previous": _rate(n, prev) if prev is not None else None, "rate_of_scans": _rate(n, first) if key != "scans" else None})
        prev = n

    day = cast(func.timezone(tz, ev.c.created_at), Date)
    rows = db.execute(select(day, ev.c.event_type, func.count()).group_by(day, ev.c.event_type)).all()
    series_map: dict[date, dict] = {}
    key_of = {et: key for key, et, _ in FUNNEL}
    for d, et, c in rows:
        if et in key_of:
            series_map.setdefault(d, {})[key_of[et]] = c
    series = fill(start, end, series_map, [k for k, _, _ in FUNNEL])

    per = {}
    for cid, et, c in db.execute(select(ev.c.campaign_id, ev.c.event_type, func.count()).group_by(ev.c.campaign_id, ev.c.event_type)).all():
        per.setdefault(cid, {})[et] = c
    campaigns = []
    for c in db.scalars(select(ReviewCampaign).where(ReviewCampaign.tenant_id == tenant_id).order_by(ReviewCampaign.created_at.desc())):
        if (campaign_id and c.id != campaign_id) or (campaign_ids is not None and c.id not in campaign_ids):
            continue
        p = per.get(c.id, {})
        campaigns.append({
            "id": str(c.id), "name": c.name, "status": c.status,
            **{key: p.get(et, 0) for key, et, _ in FUNNEL}, **{key: p.get(et, 0) for key, et in EXTRA_STATS},
            "regenerations": p.get("draft_regenerated", 0),
            "conversion": _rate(p.get("google_redirect", 0), p.get("scan", 0)),
        })
    campaigns.sort(key=lambda r: r["scans"], reverse=True)

    topics, topic_sessions = topic_popularity(db, ev, db.get(Tenant, tenant_id))
    generated, regenerated, failed = totals.get("draft_generated", 0), totals.get("draft_regenerated", 0), totals.get("generation_failed", 0)
    asked_ai = max(totals.get("ai_requested", 0), generated + failed)  # older events predate "ai_requested"
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "timezone": tz},
        "totals": {
            "scans": first, "unique_visitors": unique_visitors, "feedback_submitted": totals.get("feedback_submitted", 0),
            "ai_generation_requests": asked_ai, "ai_requested": asked_ai, "manual_selected": totals.get("manual_selected", 0),
            "needs_more": totals.get("needs_more", 0), "suggestion_sessions": topic_sessions, "drafts_generated": generated, "regenerations": regenerated,
            "generation_failures": failed, "drafts_approved": totals.get("draft_approved", 0), "review_copied": totals.get("review_copied", 0), "direct_submitted": totals.get("review_submitted", 0), "direct_submit_failed": totals.get("review_submit_failed", 0), "google_redirects": totals.get("google_redirect", 0),
        },
        "funnel": funnel, "series": series, "campaigns": campaigns, "suggestions": topics, "ai": ai_quality(db, tenant_id, lo, hi),
        "ratings": rating_distribution(db, ev),
        "definitions": {
            "ratings": "The 1-5 stars customers chose on your FlowQr review page. It is a separate number from your Google rating, which customers set on Google. It is never used to hide or route anyone.",
            "scans": "Times a campaign QR code opened the review page (bots and rapid refreshes excluded).",
            "suggestion_sessions": "Customers who picked at least one topic chip. Topics are things to comment on, not claims about their visit.",
            "feedback_submitted": "Customers who began a review, either by asking for AI help or by choosing to write it themselves.",
            "ai_requested": "Times a customer tapped 'Generate my review'.",
            "manual_selected": "Customers who chose to write their review themselves (no AI used).",
            "needs_more": "Times we asked for a little more detail instead of guessing.",
            "unique_visitors": "Distinct visitors per day (a salted daily hash; no personal data is stored).",

            "drafts_approved": "Customers who confirmed their final wording.",
            "direct_submitted": "Reviews Google itself confirmed as published through a direct-submission provider. Always 0 unless Google has approved that route for FlowHQ and it has been verified; see docs/GOOGLE_DIRECT_REVIEWS.md.",
            "review_copied": "Customers whose browser reported copying the review to the clipboard when they tapped Copy & Continue to Google. If copying is blocked they paste nothing, so this is the number to watch.",
            "google_redirects": "Taps on 'Continue to Google', once per customer. This is NOT a published review: we cannot know whether a customer posted one.",
        },
    }
