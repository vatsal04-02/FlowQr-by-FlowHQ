"""GBP Manager > Local ranking > Geo-grid: where this location appears for a search term from several points around it.

Anyone who can see the location can read the maps. Creating or removing a grid and running a scan (which spends the plan's monthly allowance of billed Google
searches) needs an owner or admin. The Places key is server-side only and never appears in any response."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import GoogleLocation, RankGrid, RankKeyword, Role
from app.services import entitlements as ent
from app.services import rank as rank_svc
from app.services import rank_grid as svc
from app.services.audit import audit

router = APIRouter(prefix="/gbp/{google_location_id}/rank/grids", tags=["rank-grid"])


def _loc(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _grid(ctx: TenantContext, gl: GoogleLocation, grid_id: uuid.UUID) -> RankGrid:
    g = ctx.db.scalar(select(RankGrid).where(RankGrid.id == grid_id, RankGrid.tenant_id == ctx.tenant_id, RankGrid.google_location_id == gl.id))
    if not g:
        raise HTTPException(status_code=404, detail="Grid not found")
    return g


def _kw(ctx: TenantContext, gl: GoogleLocation, kid: uuid.UUID) -> RankKeyword:
    k = ctx.db.scalar(select(RankKeyword).where(RankKeyword.id == kid, RankKeyword.tenant_id == ctx.tenant_id, RankKeyword.google_location_id == gl.id))
    if not k:
        raise HTTPException(status_code=404, detail="Search term not found")
    return k


def _err(exc: rank_svc.RankError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("")
def overview(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    kws = ctx.db.scalars(select(RankKeyword).where(RankKeyword.google_location_id == gl.id, RankKeyword.tenant_id == ctx.tenant_id).order_by(RankKeyword.created_at)).all()
    grids = ctx.db.scalars(select(RankGrid).where(RankGrid.google_location_id == gl.id, RankGrid.tenant_id == ctx.tenant_id).order_by(RankGrid.created_at)).all()
    out = {"configured": rank_svc.enabled(), "allowance": svc.allowance(ctx.db, ctx.tenant_id), "note": svc.NOTE, "sizes": list(svc.SIZES),
           "spacing": {"min": svc.settings.rank_grid_min_spacing_m, "max": svc.settings.rank_grid_max_spacing_m},
           "has_position": gl.lat is not None, "keywords": [{"id": str(k.id), "keyword": k.keyword} for k in kws],
           "grids": [{**svc.grid_out(g), "latest": [{"keyword_id": str(k.id), "scan": (lambda s: svc.scan_out(s) if s else None)(svc.latest_scan(ctx.db, g.id, k.id))} for k in kws]} for g in grids]}
    ctx.db.commit()
    return out


class GridIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    mode: str = Field(default="square", pattern="^(square|custom)$")
    size: int | None = None
    spacing_m: int | None = Field(default=None, ge=1, le=100_000)
    centre_lat: float | None = Field(default=None, ge=-90, le=90)
    centre_lng: float | None = Field(default=None, ge=-180, le=180)
    points: list[dict] | None = Field(default=None, max_length=100)


@router.post("", status_code=201)
def create_grid(google_location_id: uuid.UUID, body: GridIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    if (body.centre_lat is None) != (body.centre_lng is None):
        raise HTTPException(status_code=422, detail="Give both a latitude and a longitude for the centre, or neither to use the business's own position.")
    try:
        g = svc.create_grid(ctx.db, gl, name=body.name, mode=body.mode, size=body.size, spacing_m=body.spacing_m,
                            centre=(body.centre_lat, body.centre_lng) if body.centre_lat is not None else None, points=body.points, user_id=ctx.user.id)
    except rank_svc.RankError as exc:
        raise _err(exc)
    audit(ctx.db, action="rank.grid_create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_grid", entity_id=g.id, meta={"name": g.name, "points": len(g.points)})
    ctx.db.commit()
    return svc.grid_out(g)


class GridPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


@router.patch("/{grid_id}")
def patch_grid(google_location_id: uuid.UUID, grid_id: uuid.UUID, body: GridPatch, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    g.active = body.active
    audit(ctx.db, action="rank.grid_toggle", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_grid", entity_id=g.id, meta={"active": g.active})
    ctx.db.commit()
    return svc.grid_out(g)


@router.delete("/{grid_id}", status_code=204)
def delete_grid(google_location_id: uuid.UUID, grid_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    audit(ctx.db, action="rank.grid_delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_grid", entity_id=g.id, meta={"name": g.name})
    ctx.db.delete(g)
    ctx.db.commit()


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword_id: uuid.UUID


@router.get("/{grid_id}/estimate")
def estimate(google_location_id: uuid.UUID, grid_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    """What a scan of this grid would cost, before anything is spent."""
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    a = svc.allowance(ctx.db, ctx.tenant_id)
    n = len(g.points or [])
    return {"points": n, "estimated_usd": round(n * svc.settings.rank_cost_per_call_usd, 2) if svc.settings.rank_cost_per_call_usd > 0 else None, "allowance": a, "fits": n <= a["remaining"]}


@router.post("/{grid_id}/scan")
def run_scan(google_location_id: uuid.UUID, grid_id: uuid.UUID, body: ScanIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Run one search term over the whole grid now. Refused up front, with nothing spent, if the monthly allowance cannot cover every point."""
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    k = _kw(ctx, gl, body.keyword_id)
    if not rank_svc.enabled():
        raise HTTPException(status_code=503, detail="Local rank tracking isn't set up on this server.")
    if not hit(f"rankgrid:{ctx.tenant_id}", 6, 3600) or not hit(f"rankgrid-ip:{client_ip(request)}", 30, 3600):
        raise HTTPException(status_code=429, detail="Too many map scans this hour. Try again later.")
    try:
        sc = svc.scan(ctx.db, gl, g, k, source="manual")
    except rank_svc.RankError as exc:
        ctx.db.rollback()
        raise _err(exc)
    audit(ctx.db, action="rank.grid_scan", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="rank_grid", entity_id=g.id,
          meta={"keyword": k.keyword, "status": sc.status, "calls": sc.calls, "significant": bool((sc.change or {}).get("significant"))})
    ctx.db.commit()
    return {"scan": svc.scan_out(sc), "allowance": svc.allowance(ctx.db, ctx.tenant_id)}


@router.get("/{grid_id}/heatmap")
def heatmap(google_location_id: uuid.UUID, grid_id: uuid.UUID, keyword_id: uuid.UUID, scan_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    k = _kw(ctx, gl, keyword_id)
    return svc.heatmap(ctx.db, g, k, scan_id)


@router.get("/{grid_id}/history")
def history(google_location_id: uuid.UUID, grid_id: uuid.UUID, keyword_id: uuid.UUID, limit: int = Query(30, ge=1, le=100), ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "geo_ranking")
    gl = _loc(ctx, google_location_id)
    g = _grid(ctx, gl, grid_id)
    k = _kw(ctx, gl, keyword_id)
    return {"keyword": k.keyword, "grid": g.name, "scans": svc.history(ctx.db, g.id, k.id, limit)}
