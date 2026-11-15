"""GBP Manager › Local ranking: where this location appears in Google Places results for the search terms a business cares about.

Anyone who can see the location can read it. Adding or removing keywords and running a check (which spends the monthly allowance of
billed Google calls) needs an owner or admin. The Places key is server-side only and never appears in any response."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import GoogleLocation, RankCheck, RankKeyword, Role
from app.services import entitlements as ent
from app.services import rank as svc
from app.services.audit import audit

router = APIRouter(prefix="/gbp/{google_location_id}/rank", tags=["rank"])


def _loc(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _kw(ctx: TenantContext, gl: GoogleLocation, kid: uuid.UUID) -> RankKeyword:
    k = ctx.db.scalar(select(RankKeyword).where(RankKeyword.id == kid, RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id == gl.id))
    if not k:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return k


@router.get("")
def overview(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "keyword_tracking")
    gl = _loc(ctx, google_location_id)
    kws = ctx.db.scalars(select(RankKeyword).where(RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id == gl.id).order_by(RankKeyword.created_at)).all()
    out = {"configured": svc.enabled(), "usage": svc.usage(ctx.db, ctx.tenant_id), "max_keywords": svc.MAX_KEYWORDS_PER_LOCATION, "note": svc.NOTE,
           "location": {"title": gl.title, "has_place_id": bool(gl.place_id)}, "keywords": [svc.keyword_out(ctx.db, k) for k in kws]}
    ctx.db.commit()
    return out


class KeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)


@router.post("/keywords", status_code=201)
def add_keyword(google_location_id: uuid.UUID, body: KeywordIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_feature(ctx.db, ctx.tenant_id, "keyword_tracking")
    gl = _loc(ctx, google_location_id)
    try:
        word = svc.clean_keyword(body.keyword)
    except svc.RankError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    n = ctx.db.scalar(select(func.count()).select_from(RankKeyword).where(RankKeyword.google_location_id == gl.id)) or 0
    if n >= svc.MAX_KEYWORDS_PER_LOCATION:
        raise HTTPException(status_code=409, detail=f"You can track up to {svc.MAX_KEYWORDS_PER_LOCATION} search terms per location. Remove one first.")
    if ctx.db.scalar(select(RankKeyword.id).where(RankKeyword.google_location_id == gl.id, func.lower(RankKeyword.keyword) == word.lower())):
        raise HTTPException(status_code=409, detail="You are already tracking that search term.")
    k = RankKeyword(tenant_id=ctx.tenant_id, google_location_id=gl.id, keyword=word, created_by=ctx.user.id)
    ctx.db.add(k)
    ctx.db.flush()
    audit(ctx.db, action="rank.keyword_add", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_keyword", entity_id=k.id, meta={"keyword": word})
    ctx.db.commit()
    return svc.keyword_out(ctx.db, k)


@router.delete("/keywords/{keyword_id}", status_code=204)
def remove_keyword(google_location_id: uuid.UUID, keyword_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _loc(ctx, google_location_id)
    k = _kw(ctx, gl, keyword_id)
    audit(ctx.db, action="rank.keyword_remove", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_keyword", entity_id=k.id, meta={"keyword": k.keyword})
    ctx.db.delete(k)
    ctx.db.commit()


class CheckIn(BaseModel):
    keyword_id: uuid.UUID | None = None  # omit to check every keyword of the location


@router.post("/check")
def check(google_location_id: uuid.UUID, body: CheckIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Run real Places searches now. Each keyword costs one call from the month's allowance; the run stops cleanly when the allowance ends."""
    ent.require_feature(ctx.db, ctx.tenant_id, "keyword_tracking")
    gl = _loc(ctx, google_location_id)
    if not svc.enabled():
        raise HTTPException(status_code=503, detail="Local rank tracking isn't set up on this server.")
    if not hit(f"rank:{ctx.tenant_id}", 20, 3600) or not hit(f"rank-ip:{client_ip(request)}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many rank checks this hour. Try again later.")
    if body.keyword_id:
        kws = [_kw(ctx, gl, body.keyword_id)]
    else:
        kws = list(ctx.db.scalars(select(RankKeyword).where(RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id == gl.id).order_by(RankKeyword.created_at)))
    if not kws:
        raise HTTPException(status_code=422, detail="Add a search term first.")
    client = svc.get_client()
    ran, failed, stopped = 0, 0, None
    for k in kws:
        try:
            row = svc.check_keyword(ctx.db, gl, k, source="manual", client=client)
        except svc.RankError as exc:  # nothing was attempted (allowance used up or not configured)
            stopped = str(exc)
            break
        ran += 1
        failed += row.status == "error"
        ctx.db.commit()  # each measurement is saved as it completes
    audit(ctx.db, action="rank.check", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location", entity_id=gl.id, meta={"checked": ran, "failed": failed})
    ctx.db.commit()
    if ran == 0 and stopped:
        raise HTTPException(status_code=429 if "limit" in stopped else 503, detail=stopped)
    return {"checked": ran, "failed": failed, "stopped": stopped, "usage": svc.usage(ctx.db, ctx.tenant_id),
            "keywords": [svc.keyword_out(ctx.db, k) for k in kws]}


@router.get("/keywords/{keyword_id}/history")
def history(google_location_id: uuid.UUID, keyword_id: uuid.UUID, limit: int = Query(30, ge=1, le=100), ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "keyword_tracking")
    gl = _loc(ctx, google_location_id)
    k = _kw(ctx, gl, keyword_id)
    rows = ctx.db.scalars(select(RankCheck).where(RankCheck.keyword_id == k.id, RankCheck.tenant_id == ctx.tenant_id).order_by(RankCheck.checked_at.desc()).limit(limit)).all()
    return {"keyword": k.keyword, "checks": [{"checked_at": c.checked_at, "status": c.status, "rank": c.rank, "results_seen": c.results_seen, "error": c.error, "source": c.source} for c in rows]}
