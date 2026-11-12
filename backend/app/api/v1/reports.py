"""Reports: reputation, Google performance, campaigns and AI activity, with CSV and PDF export.

Only real numbers: Google performance is what the last successful Google refresh returned (with its time), and is reported as
unavailable, with the reason, when Google has not answered."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from app.api.v1.analytics import _range
from app.core.deps import TenantContext, get_tenant_context
from app.core.rate_limit import client_ip, hit
from app.models import AgentTask, AIGenerationLog, GbpSnapshot, GoogleLocation, Location, ReplyDraft, ReplyStatus, Review, ScheduledPost
from app.services import pdf_text, review_growth as rg_svc
from app.services.audit import audit

router = APIRouter(prefix="/reports", tags=["reports"])
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(v):
    """CSV cell safe to open in a spreadsheet: text starting with a formula character is neutralised (reviews are written by strangers)."""
    if v is None:
        return ""
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return "'" + s if s.startswith(FORMULA_START) else s


def build_summary(ctx: TenantContext, start: date | None, end: date | None, location_id=None) -> dict:
    start, end, lo, hi, tz = _range(ctx, start, end)
    db, t = ctx.db, ctx.tenant_id
    rq = select(Review).where(Review.tenant_id == t, Review.review_created_at >= lo, Review.review_created_at < hi, ctx.scope(Review.location_id))
    if location_id:
        rq = rq.where(Review.location_id == location_id)
    rows = db.scalars(rq).all()
    n = len(rows)
    replied = [r for r in rows if r.google_reply_text is not None]
    resp = [(r.google_reply_at - r.review_created_at).total_seconds() / 3600 for r in replied if r.google_reply_at and r.google_reply_at >= r.review_created_at]
    unanswered_now = db.scalar(select(func.count()).select_from(Review).where(Review.tenant_id == t, Review.google_reply_text.is_(None), ctx.scope(Review.location_id))) or 0
    reputation = {"reviews": n, "average_rating": round(sum(r.rating for r in rows) / n, 2) if n else None, "replied": len(replied), "reply_rate": round(len(replied) / n, 3) if n else None,
                  "avg_response_hours": round(sum(resp) / len(resp), 1) if resp else None, "unanswered_now": unanswered_now,
                  "distribution": {str(i): sum(1 for r in rows if r.rating == i) for i in range(1, 6)}}
    snaps = db.execute(select(GbpSnapshot, GoogleLocation.title).join(GoogleLocation, GoogleLocation.id == GbpSnapshot.google_location_id).where(GbpSnapshot.tenant_id == t, ctx.scope(GoogleLocation.location_id))).all()
    perf = [{"location": title, "last_28_days": s.performance["current"], "previous_28_days": s.performance["previous"], "fetched_at": s.fetched_at, "window": f'{s.performance["from"]} to {s.performance["to"]}'} for s, title in snaps if s.performance]
    google = {"available": bool(perf), "locations": perf, "note": "Customer actions on Google (calls, website clicks, directions, bookings, messages), as returned by Google at the time shown. Google's data lags a few days." if perf else
              "No Google performance data yet: Google is not connected or has not answered. Nothing is estimated.", "errors": [{"location": title, "error": s.error} for s, title in snaps if s.error]}
    campaign_totals = None
    if not ctx.restricted:
        tot = rg_svc.analytics(db, tenant_id=t, tz=tz, start=start, end=end, lo=lo, hi=hi, campaign_id=None, fill=lambda *a, **k: [], location_id=location_id)["totals"]
        campaign_totals = {k: tot[k] for k in ("scans", "unique_visitors", "feedback_submitted", "drafts_approved", "google_redirects")}
    out = {"range": {"from": start.isoformat(), "to": end.isoformat(), "timezone": tz}, "reputation": reputation, "google_performance": google, "campaigns": campaign_totals}
    if ctx.role.value != "staff":
        ai = db.execute(select(AIGenerationLog.kind, AIGenerationLog.status, func.count()).where(AIGenerationLog.tenant_id == t, AIGenerationLog.created_at >= lo, AIGenerationLog.created_at < hi).group_by(AIGenerationLog.kind, AIGenerationLog.status)).all()
        tasks = dict(db.execute(select(AgentTask.status, func.count()).where(AgentTask.tenant_id == t, AgentTask.created_at >= lo, AgentTask.created_at < hi).group_by(AgentTask.status)).all())
        posts = dict(db.execute(select(ScheduledPost.status, func.count()).where(ScheduledPost.tenant_id == t, ScheduledPost.created_at >= lo, ScheduledPost.created_at < hi).group_by(ScheduledPost.status)).all())
        pub_replies = db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == t, ReplyDraft.status == ReplyStatus.published, ReplyDraft.published_at >= lo, ReplyDraft.published_at < hi)) or 0
        out["ai_activity"] = {"ai_uses": [{"kind": k, "status": s, "count": c} for k, s, c in ai], "tasks_by_status": tasks, "posts_by_status": posts, "replies_published": pub_replies}
    return out


@router.get("/summary")
def summary(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"), location_id: str | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    import uuid
    loc = None
    if location_id:
        try:
            loc = uuid.UUID(location_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid location")
        if not ctx.can_access_location(loc) or not db_has(ctx, loc):
            raise HTTPException(status_code=404, detail="Location not found")
    return build_summary(ctx, start, end, loc)


def db_has(ctx: TenantContext, loc) -> bool:
    return bool(ctx.db.scalar(select(Location.id).where(Location.id == loc, Location.tenant_id == ctx.tenant_id)))


@router.get("/summary.pdf")
def summary_pdf(request: Request, start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"), ctx: TenantContext = Depends(get_tenant_context)):
    if not hit(f"report-pdf:{ctx.tenant_id}", 20, 3600):
        raise HTTPException(status_code=429, detail="Too many report downloads. Try again later.")
    s = build_summary(ctx, start, end)
    r, g, c = s["reputation"], s["google_performance"], s["campaigns"]
    B = [("h1", f"{ctx.tenant.name}: reputation report"), ("small", f"{s['range']['from']} to {s['range']['to']} ({s['range']['timezone']}). Generated by FlowQR. Only real data is shown; missing data is marked as such."), ("gap", ""),
         ("h2", "Reputation"), ("p", f"New reviews: {r['reviews']}\nAverage rating: {r['average_rating'] if r['average_rating'] is not None else 'no reviews in range'}\n"
                                   f"Replied: {r['replied']} ({round(100 * r['reply_rate']) if r['reply_rate'] is not None else '-'}%)\nAverage time to reply: {str(r['avg_response_hours']) + ' hours' if r['avg_response_hours'] is not None else 'not available'}\n"
                                   f"Reviews still unanswered right now: {r['unanswered_now']}\nRatings 1-5: " + ", ".join(f"{k}: {v}" for k, v in r["distribution"].items())), ("gap", ""),
         ("h2", "Google performance")]
    if g["available"]:
        B += [("p", "\n".join(f"{p['location']}: {p['last_28_days']} actions in {p['window']} (previous 28 days: {p['previous_28_days']}). Fetched {str(p['fetched_at'])[:16]}.")) for p in g["locations"]] + [("small", g["note"])]
    else:
        B += [("p", g["note"])]
    B.append(("gap", ""))
    B.append(("h2", "QR review campaigns"))
    B.append(("p", "Not shown for location-restricted accounts." if c is None else f"QR scans: {c['scans']} (unique devices: {c['unique_visitors']})\nStarted a review: {c['feedback_submitted']}\nConfirmed a review: {c['drafts_approved']}\nContinued to Google: {c['google_redirects']}\nA tap on Google is not proof a review was posted."))
    if "ai_activity" in s:
        a = s["ai_activity"]
        B += [("gap", ""), ("h2", "AI activity"), ("p", f"Replies published: {a['replies_published']}\nAI uses: {sum(x['count'] for x in a['ai_uses'])}\nAgent tasks: " + (", ".join(f"{k}: {v}" for k, v in a['tasks_by_status'].items()) or "none") +
                                                       "\nPosts: " + (", ".join(f"{k}: {v}" for k, v in a['posts_by_status'].items()) or "none"))]
    audit(ctx.db, action="report.pdf", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="report", ip=client_ip(request))
    ctx.db.commit()
    return Response(pdf_text.render(B, f"{ctx.tenant.name} report"), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="flowqr-report.pdf"', "Cache-Control": "private, no-store"})


@router.get("/export/{name}.csv")
def export_csv(name: str, request: Request, start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"), ctx: TenantContext = Depends(get_tenant_context)):
    if name not in ("reviews", "posts", "tasks", "ai"):
        raise HTTPException(status_code=404, detail="Unknown report")
    if name in ("tasks", "ai") and ctx.role.value == "staff":
        raise HTTPException(status_code=403, detail="Owners and admins only.")
    if not hit(f"report-csv:{ctx.tenant_id}", 30, 3600):
        raise HTTPException(status_code=429, detail="Too many exports. Try again later.")
    _, _, lo, hi, _ = _range(ctx, start, end)
    db, t = ctx.db, ctx.tenant_id
    buf = io.StringIO()
    w = csv.writer(buf)
    if name == "reviews":
        w.writerow(["review_date", "location", "reviewer", "rating", "review_text", "replied", "reply_text", "reply_date", "reply_state_on_google"])
        names = {l.id: l.name for l in db.scalars(select(Location).where(Location.tenant_id == t))}
        for r in db.scalars(select(Review).where(Review.tenant_id == t, Review.review_created_at >= lo, Review.review_created_at < hi, ctx.scope(Review.location_id)).order_by(Review.review_created_at.desc()).limit(50000)):
            w.writerow([_cell(x) for x in (r.review_created_at, names.get(r.location_id), r.reviewer_name, r.rating, r.text, "yes" if r.google_reply_text is not None else "no", r.google_reply_text, r.google_reply_at, r.google_reply_state)])
    elif name == "posts":
        w.writerow(["created", "location", "status", "scheduled_for", "published_at", "ai_written", "text", "failure_reason"])
        for p, title in db.execute(select(ScheduledPost, GoogleLocation.title).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id).where(
                ScheduledPost.tenant_id == t, ScheduledPost.created_at >= lo, ScheduledPost.created_at < hi, ctx.scope(GoogleLocation.location_id)).order_by(ScheduledPost.created_at.desc()).limit(50000)):
            w.writerow([_cell(x) for x in (p.created_at, title, p.status, p.scheduled_for, p.published_at, "yes" if p.generated_by_ai else "no", p.summary, p.failure_reason)])
    elif name == "tasks":
        w.writerow(["created", "kind", "title", "status", "completed_at", "failure_reason"])
        for x in db.scalars(select(AgentTask).where(AgentTask.tenant_id == t, AgentTask.created_at >= lo, AgentTask.created_at < hi).order_by(AgentTask.created_at.desc()).limit(50000)):
            w.writerow([_cell(v) for v in (x.created_at, x.kind, x.title, x.status, x.completed_at, x.failure_reason)])
    else:
        w.writerow(["when", "kind", "status", "provider", "model", "input_chars", "output_chars", "latency_ms", "error"])
        for x in db.scalars(select(AIGenerationLog).where(AIGenerationLog.tenant_id == t, AIGenerationLog.created_at >= lo, AIGenerationLog.created_at < hi).order_by(AIGenerationLog.created_at.desc()).limit(50000)):
            w.writerow([_cell(v) for v in (x.created_at, x.kind, x.status, x.provider, x.model, x.input_chars, x.output_chars, x.latency_ms, x.error)])
    audit(db, action="report.csv", tenant_id=t, user_id=ctx.user.id, entity_type="report", meta={"name": name}, ip=client_ip(request))
    db.commit()
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="flowqr-{name}.csv"', "Cache-Control": "private, no-store"})
