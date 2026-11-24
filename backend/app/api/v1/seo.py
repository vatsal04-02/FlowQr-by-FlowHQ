"""Local SEO read models: SEO overview, competitor observations and Google profile health. Read-only aggregations over data FlowQR already stores.

Nothing here calls Google. Every number carries its source:
  * "places"  = Google Places API (New) measurements already stored in rank_checks (position among the first 20 results around the location; not what every person sees in Maps).
  * "google"  = what the Business Profile APIs returned and FlowQR stored (search terms, profile fields).
  * "flowqr"  = counted or calculated by FlowQR from the two above.
Business Profile APIs do not provide a ranking position or any competitor data; none is claimed here. Staff only see the locations they are allowed to (ctx.can_access_location),
and every query is tenant-scoped on top of row-level security."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.models import GbpSnapshot, GoogleLocation, PinnedCompetitor, RankCheck, RankKeyword, Review, Role
from app.models.competitors import PIN_LIMIT_PER_LOCATION
from app.services import competitors as comp_svc
from app.models.base import utcnow
from app.services import entitlements as ent
from app.services import rank as rank_svc
from app.services.agent import health as health_svc
from app.services.agent.snapshots import profile_completeness
from app.services.audit import audit

router = APIRouter(prefix="/seo", tags=["local-seo"])

SOURCES = {"places": "Google Places API (measured)", "google": "Google Business Profile (as reported by Google)", "flowqr": "Calculated by FlowQR"}
TOP_N = 10


def _glocs(ctx: TenantContext, location_id: uuid.UUID | None) -> list[GoogleLocation]:
    q = select(GoogleLocation).where(GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True))
    if location_id:
        q = q.where(GoogleLocation.location_id == location_id)
    return [g for g in ctx.db.scalars(q.order_by(GoogleLocation.title)) if ctx.can_access_location(g.location_id)]


def _tracking_allowed(ctx: TenantContext) -> bool:
    try:
        ent.require_feature(ctx.db, ctx.tenant_id, "keyword_tracking")
        return True
    except HTTPException:
        return False


def _rank_label(rank: int | None) -> str:
    return "Not in the first 20" if rank is None else f"#{rank}"


# ------------------------------------------------------------------------------------------------------------------------------ SEO overview
@router.get("/overview")
def seo_overview(location_id: uuid.UUID | None = None, days: int = Query(90, ge=7, le=365), ctx: TenantContext = Depends(get_tenant_context)):
    glocs = _glocs(ctx, location_id)
    db = ctx.db
    out: dict = {"sources": SOURCES, "locations": [{"id": str(g.id), "title": g.title} for g in glocs], "provider_configured": rank_svc.enabled(), "tracking_allowed": _tracking_allowed(ctx)}
    if not glocs:
        out.update(state="no_location", keywords=[], summary=None, trend=[], google_terms=None, attention=[])
        return out

    kws = list(db.scalars(select(RankKeyword).where(RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id.in_([g.id for g in glocs])).order_by(RankKeyword.created_at)))
    title = {g.id: g.title for g in glocs}
    rows = []
    for k in kws:
        o = rank_svc.keyword_out(db, k)
        latest = o["latest"]
        rows.append({"id": o["id"], "keyword": k.keyword, "location": title.get(k.google_location_id), "status": latest["status"] if latest else None, "rank": latest["rank"] if latest else None,
                     "previous_rank": o["previous_rank"], "change": o["change"], "checked_at": latest["checked_at"] if latest else None, "error": latest["error"] if latest else None})
    measured = [r for r in rows if r["status"] == "ok"]
    summary = {"tracked": len(rows), "measured": len(measured), "never_measured": sum(1 for r in rows if r["status"] is None), "failed": sum(1 for r in rows if r["status"] == "error"),
               "top3": sum(1 for r in measured if r["rank"] and r["rank"] <= 3), "top10": sum(1 for r in measured if r["rank"] and r["rank"] <= 10),
               "top20": sum(1 for r in measured if r["rank"]), "not_found": sum(1 for r in measured if r["rank"] is None),
               "last_checked_at": max((r["checked_at"] for r in rows if r["checked_at"]), default=None), "source": "places", "note": rank_svc.NOTE}

    # trend: for each day, the share of tracked terms (that were measured that day) showing the business in the first 10 results. Days with no measurement have no point.
    since = utcnow() - timedelta(days=days)
    ok_checks = db.execute(select(RankCheck.keyword_id, RankCheck.checked_at, RankCheck.rank).where(
        RankCheck.tenant_id == ctx.tenant_id, RankCheck.keyword_id.in_([k.id for k in kws] or [uuid.uuid4()]), RankCheck.status == "ok", RankCheck.checked_at >= since).order_by(RankCheck.checked_at)).all()
    per_day: dict[str, dict[uuid.UUID, int | None]] = defaultdict(dict)
    for kid, at, rank in ok_checks:
        per_day[at.date().isoformat()][kid] = rank  # the last measurement of the day wins
    trend = [{"date": d, "measured": len(m), "top3": sum(1 for r in m.values() if r and r <= 3), "top10": sum(1 for r in m.values() if r and r <= 10)} for d, m in sorted(per_day.items())]

    # Google's own search terms (monthly impressions), from the last successful refresh. This is NOT a position.
    terms: dict[str, dict] = {}
    months: list[str] = []
    fetched = []
    for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.tenant_id == ctx.tenant_id, GbpSnapshot.google_location_id.in_([g.id for g in glocs]))):
        perf = s.performance or {}
        for t in perf.get("keywords") or []:
            key = (t.get("keyword") or "").strip().lower()
            if not key:
                continue
            cur = terms.setdefault(key, {"keyword": t.get("keyword"), "value": 0, "small": False})
            if t.get("value") is None:
                cur["small"] = True  # Google reports small counts as "fewer than N": no number is shown
            else:
                cur["value"] += int(t["value"])
        months = perf.get("keywords_months") or months
        if s.fetched_at:
            fetched.append(s.fetched_at)
    tracked_words = {k.keyword.strip().lower() for k in kws}
    google_terms = None
    if terms:
        ranked = sorted(terms.values(), key=lambda t: (-t["value"], t["keyword"] or ""))
        google_terms = {"terms": [{**t, "tracked": (t["keyword"] or "").strip().lower() in tracked_words, "value": t["value"] or None} for t in ranked[:20]], "months": months,
                        "fetched_at": max(fetched).isoformat() if fetched else None, "source": "google",
                        "note": "Search terms people used before seeing your profile, as Google reports them (monthly impressions). This is not a ranking position."}

    attention = []
    for r in rows:
        if r["status"] == "error":
            attention.append({"kind": "check_failed", "keyword": r["keyword"], "detail": "The last check could not be measured: " + (r["error"] or "unknown error"), "source": "places"})
        elif r["status"] is None:
            attention.append({"kind": "never_measured", "keyword": r["keyword"], "detail": "Not measured yet.", "source": "places"})
        elif r["rank"] is None:
            attention.append({"kind": "not_found", "keyword": r["keyword"], "detail": "Not in the first 20 results at the last check.", "source": "places"})
        elif r["change"] is not None and r["change"] < 0:
            attention.append({"kind": "dropped", "keyword": r["keyword"], "detail": f"Moved down {abs(r['change'])} {'place' if abs(r['change']) == 1 else 'places'} (now {_rank_label(r['rank'])}).", "source": "places"})
    if google_terms:
        for t in google_terms["terms"][:10]:
            if not t["tracked"] and t["value"]:
                attention.append({"kind": "untracked_term", "keyword": t["keyword"], "detail": f"{t['value']} people searched this before seeing your profile, and you do not track it.", "source": "google"})
    out.update(state="ok" if rows else "no_keywords", keywords=rows, summary=summary, trend=trend, google_terms=google_terms, attention=attention[:12])
    return out


# ------------------------------------------------------------------------------------------------------------------------------ competitors (stage 1)
@router.get("/competitors")
def competitors(location_id: uuid.UUID | None = None, days: int = Query(180, ge=7, le=365), ctx: TenantContext = Depends(get_tenant_context)):
    """Stage 1: nothing new is requested from Google. Competitors are the other businesses that appeared in the stored Places results for your tracked terms, with the rating
    and review count observed on each date. Changes are the difference between the first and the latest observation in the window, never an estimate."""
    glocs = _glocs(ctx, location_id)
    out: dict = {"stage": 2, "pinned": [], "pin_limit": PIN_LIMIT_PER_LOCATION, "source": "places", "sources": SOURCES, "provider_configured": rank_svc.enabled(), "competitors": [], "you": None, "observations": 0, "window_days": days,
                 "note": "Observed in Google Places search results for your tracked search terms. Ratings and review counts are what Google returned on the dates shown; FlowQR does not "
                         "estimate anything between observations. Google Business Profile APIs do not provide competitor data."}
    if not glocs:
        out["state"] = "no_location"
        return out
    kws = {k.id: k for k in ctx.db.scalars(select(RankKeyword).where(RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id.in_([g.id for g in glocs])))}
    since = utcnow() - timedelta(days=days)
    checks = list(ctx.db.scalars(select(RankCheck).where(RankCheck.tenant_id == ctx.tenant_id, RankCheck.keyword_id.in_(list(kws) or [uuid.uuid4()]), RankCheck.status == "ok",
                                                         RankCheck.checked_at >= since).order_by(RankCheck.checked_at)))
    if not checks:
        out["state"] = "no_observations" if kws else "no_keywords"
        return out
    comp: dict[str, dict] = {}
    you_obs = []
    pinned_rows = list(ctx.db.scalars(select(PinnedCompetitor).where(PinnedCompetitor.tenant_id == ctx.tenant_id, PinnedCompetitor.google_location_id.in_([g.id for g in glocs])).order_by(PinnedCompetitor.created_at)))
    pinned_keys = {(r.place_id, r.google_location_id) for r in pinned_rows}
    out["pinned"] = [comp_svc.out(ctx.db, r) for r in pinned_rows]
    out["pin_limit"] = PIN_LIMIT_PER_LOCATION
    for c in checks:
        kw = kws[c.keyword_id].keyword
        entries = [p for p in (c.top_results or []) if not p.get("is_you")]
        mine = next((p for p in (c.top_results or []) if p.get("is_you")), None)
        for i, p in enumerate(entries, 1):
            key = p.get("place_id") or p.get("name")
            if not key:
                continue
            e = comp.setdefault(key, {"place_id": p.get("place_id"), "name": p.get("name"), "obs": [], "keywords": {}, "locs": set()})
            e["locs"].add(c.google_location_id)
            e["name"] = p.get("name") or e["name"]
            e["obs"].append({"at": c.checked_at, "rating": p.get("rating"), "reviews": p.get("reviews")})
            kd = e["keywords"].setdefault(kw, {"keyword": kw, "seen": 0, "best_position": i, "ahead_of_you": 0, "your_checks": 0})
            kd["seen"] += 1
            kd["best_position"] = min(kd["best_position"], i)
            kd["your_checks"] += 1
            if c.rank is None or i < c.rank:
                kd["ahead_of_you"] += 1  # they were above you (or you were not in the first 20) at this check
        if mine:
            you_obs.append({"at": c.checked_at, "rating": mine.get("rating"), "reviews": mine.get("reviews"), "rank": c.rank, "keyword": kw})
    out["observations"] = len(checks)

    def trend(obs):
        pts = [o for o in obs if o["reviews"] is not None]
        if len(pts) < 2 or pts[0]["at"].date() == pts[-1]["at"].date():
            return None  # one observation (or one day) is not a change
        rr = [o for o in obs if o["rating"] is not None]
        return {"reviews_change": pts[-1]["reviews"] - pts[0]["reviews"], "from": pts[0]["at"].isoformat(), "to": pts[-1]["at"].isoformat(),
                "rating_change": round(rr[-1]["rating"] - rr[0]["rating"], 1) if len(rr) >= 2 else None}

    items = []
    for e in comp.values():
        last = e["obs"][-1]
        items.append({"place_id": e["place_id"], "name": e["name"], "google_location_ids": sorted(str(x) for x in e["locs"]), "pinned": (e["place_id"], next(iter(e["locs"]))) in pinned_keys,
                      "rating": last["rating"], "reviews": last["reviews"], "observed_at": last["at"].isoformat(),
                      "first_observed_at": e["obs"][0]["at"].isoformat(), "observations": len(e["obs"]), "change": trend(e["obs"]),
                      "keywords": sorted(e["keywords"].values(), key=lambda k: (k["best_position"], k["keyword"]))[:8]})
    items.sort(key=lambda i: (-sum(k["seen"] for k in i["keywords"]), -(i["reviews"] or 0)))
    out["competitors"] = items[:30]
    if you_obs:
        last = you_obs[-1]
        out["you"] = {"rating": last["rating"], "reviews": last["reviews"], "observed_at": last["at"].isoformat(), "change": trend(you_obs)}
    out["state"] = "ok"
    # evidence-based opportunities only: stated with the numbers they rest on
    opp = []
    if out["you"] and out["you"]["reviews"] is not None:
        ahead = [i for i in items if i["reviews"] is not None and i["keywords"] and i["keywords"][0]["best_position"] <= 3 and i["reviews"] > out["you"]["reviews"]]
        if ahead:
            most = max(i["reviews"] for i in ahead)
            opp.append({"kind": "review_gap", "detail": f"{len(ahead)} business{'es' if len(ahead) != 1 else ''} in the top 3 for your tracked terms {'have' if len(ahead) != 1 else 'has'} more reviews than you "
                                                         f"(up to {most} against your {out['you']['reviews']}), as last observed."})
    out["opportunities"] = opp
    return out


# ------------------------------------------------------------------------------------------------------------------------------ profile health
def _check(key, label, status, detail, link=None, weight=None):
    return {"key": key, "label": label, "status": status, "detail": detail, "link": link, "weight": weight}


# A row that can be fixed opens the change FlowQR prepares for it (`/ai/changes` drafts it on arrival, shows BEFORE and AFTER and the approval), never the generic editor, which showed the
# same page whatever was clicked. `editor` is where the owner can still make the change by hand; the change page offers it when nothing can be prepared.
PREPARE_AREA = {"description": "description", "hours": "hours", "phone": "contacts", "website": "contacts", "category": "categories", "additional_categories": "categories", "services": "services"}


def _fix_link(key: str, gid) -> str | None:
    area = PREPARE_AREA.get(key)
    return f"/ai/changes?prepare={area}&location={gid}" if area else None


@router.get("/profile-health")
def profile_health(location_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    """A checklist per location built from the last profile Google returned (GbpSnapshot), plus the existing Business Health Score and its formula. A location FlowQR has not
    received a profile for is "unavailable", never scored as failing."""
    glocs = _glocs(ctx, location_id)
    db = ctx.db
    out: dict = {"sources": SOURCES, "locations": [], "health": None}
    if not glocs:
        out["state"] = "no_location"
        return out
    snaps = {s.google_location_id: s for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.tenant_id == ctx.tenant_id, GbpSnapshot.google_location_id.in_([g.id for g in glocs])))}
    now = utcnow()
    for g in glocs:
        s = snaps.get(g.id)
        unanswered = db.scalar(select(func.count()).select_from(Review).where(Review.tenant_id == ctx.tenant_id, Review.location_id == g.location_id, Review.google_reply_text.is_(None))) if g.location_id else None
        item = {"id": str(g.id), "title": g.title, "state": "ok", "fetched_at": s.fetched_at.isoformat() if s and s.fetched_at else None, "error": s.error if s else None, "checks": [], "completeness": None}
        if not s or not s.info:
            item.update(state="unavailable", reason="Google has not shared this profile with FlowQr yet." + (f" ({s.error})" if s and s.error else ""))
            out["locations"].append(item)
            continue
        info = s.info
        comp = profile_completeness(info)
        item["completeness"] = comp["percent"]
        desc = (info.get("description") or "").strip()
        services = info.get("services") or []
        extra = info.get("additional_categories") or []
        checks = [
            _check("description", "Business description", "ok" if len(desc) >= 250 else "warn" if desc else "missing", f"{len(desc)} characters" if desc else "No description yet.", _fix_link("description", g.id), 30),
            _check("hours", "Opening hours", "ok" if info.get("hours") else "missing", "Weekly hours are set." if info.get("hours") else "No weekly hours.", _fix_link("hours", g.id), 25),
            _check("phone", "Phone number", "ok" if (info.get("phone") or "").strip() else "missing", "Set." if (info.get("phone") or "").strip() else "No phone number.", _fix_link("phone", g.id), 15),
            _check("website", "Website", "ok" if (info.get("website") or "").strip() else "missing", "Set." if (info.get("website") or "").strip() else "No website link.", _fix_link("website", g.id), 15),
            _check("category", "Main category", "ok" if info.get("primary_category") else "missing", (info.get("primary_category") or {}).get("name") if isinstance(info.get("primary_category"), dict) else (info.get("primary_category") or "No main category."), "/gbp/info", 15),
            _check("additional_categories", "Additional categories", "ok" if extra else "warn", f"{len(extra)} added." if extra else "None added. Extra categories help you appear for related searches.", _fix_link("additional_categories", g.id)),
            _check("services", "Services listed", "ok" if services else "warn", f"{len(services)} listed." if services else "No services listed on the profile.", _fix_link("services", g.id)),
        ]
        media = s.media or []
        newest = max((m.get("created_at") for m in media if m.get("created_at")), default=None)
        checks.append(_check("photos", "Photos", "ok" if len(media) >= 5 else "warn" if media else "missing", f"{len(media)} on the profile." if media else "No photos on the profile.", "/gbp/photos"))
        if newest:
            checks[-1]["detail"] += f" Newest added {str(newest)[:10]}."
        posts = s.posts or []
        newest_post = max((p.get("created_at") for p in posts if p.get("created_at")), default=None)
        recent = False
        if newest_post:
            try:
                from datetime import datetime
                recent = (now - datetime.fromisoformat(str(newest_post).replace("Z", "+00:00"))).days <= 30
            except ValueError:
                recent = False
        checks.append(_check("posts", "Recent post", "ok" if recent else "warn", f"Latest post {str(newest_post)[:10]}." if newest_post else "No posts yet.", "/gbp/posts"))
        if unanswered is not None:
            checks.append(_check("unanswered", "Unanswered reviews", "ok" if unanswered == 0 else "warn", "Every review has a reply." if unanswered == 0 else f"{unanswered} review{'s' if unanswered != 1 else ''} without a reply.", "/gbp/reviews?state=none"))
        item["checks"] = checks
        out["locations"].append(item)
    out["state"] = "ok"
    out["health"] = health_svc.compute(db, ctx.tenant, location_ids=ctx.location_ids)
    return out


# ------------------------------------------------------------------------------------------------------------------------------ competitors (stage 2): pin / unpin
class PinIn(BaseModel):
    google_location_id: uuid.UUID
    place_id: str = Field(min_length=1, max_length=200)


@router.post("/competitors/pinned", status_code=201)
def pin_competitor(body: PinIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Follow a business that has appeared next to you. Owner or admin. It reads stored results only: no Google call is made and nothing is billed."""
    gl = next((g for g in _glocs(ctx, None) if g.id == body.google_location_id), None)
    if gl is None:
        raise HTTPException(status_code=404, detail="Google location not found")
    try:
        row = comp_svc.pin(ctx.db, gl, body.place_id, user_id=ctx.user.id)
    except rank_svc.RankError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    audit(ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="competitor.pin", entity_type="pinned_competitor", entity_id=str(row.id), meta={"place_id": row.place_id, "name": row.name})
    out = comp_svc.out(ctx.db, row)
    ctx.db.commit()
    return out


@router.delete("/competitors/pinned/{pinned_id}", status_code=204)
def unpin_competitor(pinned_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    row = ctx.db.scalar(select(PinnedCompetitor).where(PinnedCompetitor.id == pinned_id, PinnedCompetitor.tenant_id == ctx.tenant_id))
    gl = ctx.db.get(GoogleLocation, row.google_location_id) if row else None
    if not row or not gl or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    comp_svc.unpin(ctx.db, row)
    audit(ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="competitor.unpin", entity_type="pinned_competitor", entity_id=str(pinned_id), meta={"place_id": row.place_id})
    ctx.db.commit()
