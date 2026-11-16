"""Business Profile management. Only operations Google's APIs support and the granted scope allows.
Every write is audited, and the response always reflects what *Google* returned, never what we sent."""
import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, Role, Tenant
from app.schemas.gbp import LocationInfoUpdate, MediaIn, PostIn
from app.services import entitlements as ent
from app.services import google as g
from app.services.agent import content_exec, executor
from app.services.audit import audit
from app.services import gbp_metrics
from app.services.google.provider import PERFORMANCE_METRICS
from app.services.google import tokens
from app.services.google.tokens import get_access_token

log = logging.getLogger("flowqr.gbp")
router = APIRouter(prefix="/gbp/{google_location_id}", tags=["google-business-profile"])


def _gloc(ctx: TenantContext, gid: uuid.UUID) -> tuple[GoogleLocation, GoogleConnection]:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    conn = ctx.db.get(GoogleConnection, gl.connection_id)
    if not conn or conn.status != GoogleConnectionStatus.active:
        raise HTTPException(status_code=409, detail="This Google connection isn't active. Reconnect Google first.")
    return gl, conn


def _call(ctx: TenantContext, conn: GoogleConnection, fn):
    """Run a provider call, mapping Google errors to honest HTTP errors."""
    try:
        provider = g.get_google_provider()
        token = get_access_token(ctx.db, conn, provider)
        return fn(provider, token)
    except g.GoogleApiNotApproved as exc:
        message = tokens.note_not_approved(conn, exc)
        ctx.db.commit()
        raise HTTPException(status_code=409, detail={"code": "google_api_" + conn.api_access, "message": message + " Nothing was changed."})
    except g.GoogleNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "google_config_pending", "message": "Google integration is awaiting configuration."})
    except g.GoogleAuthRevoked:
        raise HTTPException(status_code=409, detail="Google access was revoked. Please reconnect.")
    except g.GoogleRateLimited:
        raise HTTPException(status_code=429, detail="Google rate limit reached. Try again in a few minutes.")
    except g.GoogleAPIError as exc:
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail="Google denied this request. The connected Google account may not manage this "
                                "location (or Business Profile is turned off for its Workspace organisation). Nothing was changed.")
        if exc.status == 400:
            raise HTTPException(status_code=422, detail=f"Google rejected this change: {str(exc)[:200]}")
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="Google couldn't find this item.")
        raise HTTPException(status_code=502, detail=f"Google error ({exc.status}). Nothing was changed.")


def _write_budget(gl: GoogleLocation) -> None:
    """Google allows 10 edits per minute per Business Profile and will not raise it. Stop the 11th here instead of
    spending a request to be told no."""
    if not hit(f"gbp-edit:{gl.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Google allows 10 profile edits per minute per location. Try again in a minute.")


def _need(ctx: TenantContext, feature: str) -> None:
    ent.require_feature(ctx.db, ctx.tenant_id, feature)


def _governed(ctx: TenantContext, gl: GoogleLocation, conn: GoogleConnection, *, kind: str, action_type: str, feature: str, content: dict, label: str, call, verify):
    """A person acting directly (these screens publish at once, with no schedule): the SAME governance as everything else. The acting user is the approver; the platform
    emergency stop applies; the action is recorded with a claim, a read-back from Google and tamper-evident history. `call(provider, token)` is the Google call exactly as
    before (its errors are still mapped by `_call`); `verify` is a separate read."""
    box: dict = {}

    def send():
        box["result"] = _call(ctx, conn, call)
        return "done", {"name": (box["result"] or {}).get("name"), "_gloc": (gl.google_account_name, gl.google_location_name)}

    out = content_exec.direct(ctx.db, kind=kind, action_type=action_type, tenant_id=ctx.tenant_id, gloc=gl, user_id=ctx.user.id, role=ctx.role, feature=feature, content=content,
                              label=label, send=send, verify=verify)
    if out["outcome"] == "held":
        raise HTTPException(status_code=503 if out.get("reason") == "emergency_stop" else 409, detail=out.get("detail") or "This cannot be sent right now.")
    if out["outcome"] == "skipped":
        raise HTTPException(status_code=409, detail="That exact change was just sent. Refresh to see it.")
    return box.get("result") if "result" in box else (out.get("payload") or {})


def _post_gone(name: str):
    def check(provider, token, payload) -> dict:
        gone = all(p.get("name") != name for p in provider.list_posts(token, payload["_gloc"][0], payload["_gloc"][1]))
        return {"matched": gone, "detail": "Google no longer lists the post." if gone else "Google still lists the post."}
    return check


def _post_has(name: str, summary: str):
    def check(provider, token, payload) -> dict:
        found = next((p for p in provider.list_posts(token, payload["_gloc"][0], payload["_gloc"][1]) if p.get("name") == name), None)
        ok = found is not None and " ".join((found.get("summary") or "").split()) == " ".join(summary.split())
        return {"matched": ok, "detail": "Google shows the edited post." if ok else "Google does not show the edited text yet."}
    return check


def _media_state(name: str, present: bool):
    def check(provider, token, payload) -> dict:
        here = any(m.get("name") == name for m in provider.list_media(token, payload["_gloc"][0], payload["_gloc"][1]))
        return {"matched": here == present, "detail": ("Google lists the photo." if here else "Google no longer lists the photo.") if here == present else
                ("Google does not list the photo yet." if present else "Google still lists the photo.")}
    return check


@router.get("/info")
def info(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _need(ctx, "gbp_info")
    gl, conn = _gloc(ctx, google_location_id)
    ctx.db.commit()
    return _call(ctx, conn, lambda p, t: p.get_location_details(t, gl.google_location_name))


@router.patch("/info")
def update_info(google_location_id: uuid.UUID, body: LocationInfoUpdate, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _need(ctx, "gbp_info")
    gl, conn = _gloc(ctx, google_location_id)
    changes = body.model_dump(exclude_unset=True)
    if "hours" in changes:
        changes["hours"] = [h if isinstance(h, dict) else h.model_dump() for h in changes["hours"]]
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    # Governed like every other profile change: read what Google holds NOW, classify each field by policy, authorise it as this person, write, read back, record.
    live = _call(ctx, conn, lambda p, t: p.get_location_details(t, gl.google_location_name))
    try:
        res = executor.owner_edit(ctx.db, ctx.db.get(Tenant, ctx.tenant_id), gl, user_id=ctx.user.id, role=ctx.role, changes=changes, live=live)
    except executor.ActionError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc))
    audit(ctx.db, action="gbp.update_info", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location", entity_id=gl.id,
          meta={"fields": sorted(changes), "applied": res["applied"], "failed": (res["failed"] or {}).get("field")}, ip=client_ip(request))
    ctx.db.commit()
    if (f := res["failed"]):
        http, detail = f.get("http"), f.get("detail") or "Google did not accept the change. Nothing was confirmed."
        if f.get("google_error") == "GoogleApiNotApproved":
            raise HTTPException(status_code=409, detail={"code": "google_api_" + conn.api_access, "message": detail + " Nothing was changed."})
        if f.get("status") == "approved" and f.get("reason") == "rate_limited":
            raise HTTPException(status_code=429, detail="Google allows 10 profile edits per minute per location. Try again in a minute.")
        if f.get("reason") == "read_back_mismatch":
            raise HTTPException(status_code=502, detail=detail)
        raise HTTPException(status_code={400: 422, 401: 403, 403: 403, 404: 404, 429: 429}.get(http, 502), detail=detail)
    return _call(ctx, conn, lambda p, t: p.get_location_details(t, gl.google_location_name))  # what Google holds now


@router.get("/categories")
def categories(google_location_id: uuid.UUID, q: str = Query(min_length=2, max_length=60), ctx: TenantContext = Depends(get_tenant_context)):
    _need(ctx, "gbp_info")
    gl, conn = _gloc(ctx, google_location_id)
    ctx.db.commit()
    return _call(ctx, conn, lambda p, t: p.search_categories(t, q))


@router.get("/posts")
def list_posts(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _need(ctx, "gbp_posts")
    gl, conn = _gloc(ctx, google_location_id)
    ctx.db.commit()
    return _call(ctx, conn, lambda p, t: p.list_posts(t, gl.google_account_name, gl.google_location_name))


@router.post("/posts", status_code=201)
def create_post(google_location_id: uuid.UUID, body: PostIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _need(ctx, "gbp_posts")
    gl, conn = _gloc(ctx, google_location_id)
    _write_budget(gl)
    created = _governed(ctx, gl, conn, kind="dpost", action_type="publish_content", feature="gbp_posts", label="Google Post",
                        content={"summary": body.summary, "cta_type": body.cta_type, "cta_url": body.cta_url},
                        call=lambda p, t: p.create_post(t, gl.google_account_name, gl.google_location_name, body.model_dump()), verify=content_exec._verify_post(body.summary))
    audit(ctx.db, action="gbp.post_create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location",
          entity_id=gl.id, meta={"post": created.get("name"), "chars": len(body.summary)}, ip=client_ip(request))
    ctx.db.commit()
    return created


@router.patch("/posts")
def update_post(google_location_id: uuid.UUID, body: PostIn, request: Request, name: str = Query(max_length=300),
                ctx: TenantContext = Depends(require_role(Role.admin))):
    """Edit an existing post (summary and button). The response is what Google returned, not what we sent."""
    _need(ctx, "gbp_posts")
    gl, conn = _gloc(ctx, google_location_id)
    if not name.startswith(f"{gl.google_account_name}/{gl.google_location_name}/localPosts/"):
        raise HTTPException(status_code=404, detail="Post not found for this location")
    payload = {"summary": body.summary, "cta_type": body.cta_type, "cta_url": body.cta_url}
    _write_budget(gl)
    updated = _governed(ctx, gl, conn, kind="dpostedit", action_type="content_edit", feature="gbp_posts", label="Google Post edit", content={"post": name, **payload},
                        call=lambda p, t: p.update_post(t, name, payload), verify=_post_has(name, body.summary))
    audit(ctx.db, action="gbp.post_update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location",
          entity_id=gl.id, meta={"post": name, "chars": len(body.summary)}, ip=client_ip(request))
    ctx.db.commit()
    return updated


@router.delete("/posts", status_code=204)
def delete_post(google_location_id: uuid.UUID, name: str = Query(max_length=300),
                ctx: TenantContext = Depends(require_role(Role.admin))):
    _need(ctx, "gbp_posts")
    gl, conn = _gloc(ctx, google_location_id)
    if not name.startswith(f"{gl.google_account_name}/{gl.google_location_name}/localPosts/"):
        raise HTTPException(status_code=404, detail="Post not found for this location")  # can't delete other locations' posts
    _write_budget(gl)
    _governed(ctx, gl, conn, kind="dpostdel", action_type="content_delete", feature="gbp_posts", label="Google Post deletion", content={"post": name},
              call=lambda p, t: p.delete_post(t, name) or {"name": name}, verify=_post_gone(name))
    audit(ctx.db, action="gbp.post_delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location", entity_id=gl.id, meta={"post": name})
    ctx.db.commit()


@router.get("/media")
def list_media(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _need(ctx, "gbp_media")
    gl, conn = _gloc(ctx, google_location_id)
    ctx.db.commit()
    return _call(ctx, conn, lambda p, t: p.list_media(t, gl.google_account_name, gl.google_location_name))


@router.post("/media", status_code=201)
def add_media(google_location_id: uuid.UUID, body: MediaIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _need(ctx, "gbp_media")
    gl, conn = _gloc(ctx, google_location_id)
    _write_budget(gl)
    box: dict = {}

    def add(p, t):
        box["m"] = p.add_media(t, gl.google_account_name, gl.google_location_name, body.source_url, body.category)
        return box["m"]

    created = _governed(ctx, gl, conn, kind="dphoto", action_type="upload_photo", feature="gbp_media", label="photo", content={"source_url": body.source_url, "category": body.category},
                        call=add, verify=lambda provider, token, payload: _media_state(payload.get("name"), True)(provider, token, payload))
    audit(ctx.db, action="gbp.media_add", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location",
          entity_id=gl.id, meta={"category": body.category}, ip=client_ip(request))
    ctx.db.commit()
    return created


@router.delete("/media", status_code=204)
def delete_media(google_location_id: uuid.UUID, name: str = Query(max_length=300), ctx: TenantContext = Depends(require_role(Role.admin))):
    _need(ctx, "gbp_media")
    gl, conn = _gloc(ctx, google_location_id)
    if not name.startswith(f"{gl.google_account_name}/{gl.google_location_name}/media/"):
        raise HTTPException(status_code=404, detail="Photo not found for this location")
    _write_budget(gl)
    _governed(ctx, gl, conn, kind="dphotodel", action_type="content_delete", feature="gbp_media", label="photo deletion", content={"media": name},
              call=lambda p, t: p.delete_media(t, name) or {"name": name}, verify=_media_state(name, False))
    audit(ctx.db, action="gbp.media_delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location", entity_id=gl.id, meta={"media": name})
    ctx.db.commit()


@router.get("/keywords")
def keywords(google_location_id: uuid.UUID, months: int = Query(3, ge=1, le=12), ctx: TenantContext = Depends(get_tenant_context)):
    """Search terms people used before seeing this profile (Performance API, monthly). Google gives an exact count only above a privacy
    threshold; below it Google only says "fewer than N", which is shown as such and never turned into a number."""
    _need(ctx, "gbp_performance")
    gl, conn = _gloc(ctx, google_location_id)
    today = date.today()
    end_y, end_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)  # last complete month
    total = end_y * 12 + end_m - 1 - (months - 1)
    start_y, start_m = total // 12, total % 12 + 1
    ctx.db.commit()
    rows = _call(ctx, conn, lambda p, t: p.search_keywords(t, gl.google_location_name, f"{start_y}-{start_m:02d}", f"{end_y}-{end_m:02d}"))
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0), -(r["below"] or 0), r["keyword"] or ""))
    return {"from_month": f"{start_y}-{start_m:02d}", "to_month": f"{end_y}-{end_m:02d}", "keywords": rows,
            "note": "Unique people who searched each term and then saw this profile, summed over the months shown, as reported by Google. "
                    "Small counts are only given by Google as 'fewer than N'."}


@router.get("/performance")
def performance(google_location_id: uuid.UUID, start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
                ctx: TenantContext = Depends(get_tenant_context)):
    """Google-reported Search/Maps impressions and actions. Data is delayed by Google and is NOT linked to FlowQR scans."""
    _need(ctx, "gbp_performance")
    gl, conn = _gloc(ctx, google_location_id)
    end = end or date.today() - timedelta(days=3)  # Google's data lags a few days
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 540:
        raise HTTPException(status_code=422, detail="Invalid date range")
    ctx.db.commit()
    series = _call(ctx, conn, lambda p, t: p.fetch_performance(t, gl.google_location_name, start.isoformat(), end.isoformat(), PERFORMANCE_METRICS))
    totals = {m: sum(pt["value"] for pt in pts) for m, pts in series.items()}
    gbp_metrics.record(ctx.db, gl, series)  # a successful answer from Google is kept, exactly as the daily job keeps it, so every page shows the same numbers
    ctx.db.commit()
    return {"from": start.isoformat(), "to": end.isoformat(), "totals": totals, "series": series,
            "note": "Reported by Google Business Profile; typically delayed by a few days. Not the same as FlowQR card scans."}
