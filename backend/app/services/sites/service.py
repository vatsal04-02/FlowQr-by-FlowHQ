"""Website builder: everything that reads or changes a site, in one place. The API layer only checks who is calling and turns SiteError into an HTTP answer.

Rules enforced here (each one has a test):
  * a site belongs to exactly one business; every query is by site or tenant id, so one business can never see another's site, images or enquiries
  * hosting is never silently free: a site is created with an explicit commercial status (`complimentary` needs a written reason), and every later change is audited with its reason
  * only a validated snapshot is ever published; a draft is never reachable from outside
  * a failed publish leaves the previous version live and the failure on record; nothing half-uploaded is ever served
  * an expired site stays up for a grace period (SITES_GRACE_DAYS); a lapse suspends the site, it never deletes content
  * a released site name is held for 90 days; deleting a business takes its website offline first and fails loudly if it cannot
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import logging
import re
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.models import Location, Site, SiteAsset, SiteDomain, SiteEnquiry, SiteRevision, SiteSlugQuarantine, Tenant
from app.models.base import utcnow
from app.schemas.common import normalize_phone
from app.services import registration
from app.services.audit import audit
from app.services.sites import catalog as C
from app.services.sites import content as CT
from app.services.sites import hosting, media, render, rules

log = logging.getLogger("flowqr.sites")
_INVISIBLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

# Reference prices (rupees). Shown to administrators for orientation only. NOTHING bills against them: no billing is connected and the commercial status is recorded by hand.
PRICING_REFERENCE = {"monthly_inr": 199, "annual_inr": 1999, "setup_inr": 0, "edits_included_per_month": 2, "billing_connected": False,
                     "note": "Reference only. Website hosting is a separate add-on, not part of Launch, Growth or Scale. Record the status by hand; nothing is charged by FlowQR."}


class SiteError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.extra = status, code, extra

    def detail(self) -> dict:
        return {"code": self.code, "message": str(self), **self.extra}


def require_enabled() -> None:
    if not settings.sites_enabled:
        raise SiteError(409, "sites_disabled", "Websites are switched off on this server.")


def public_config() -> dict:
    return {"enabled": settings.sites_enabled, "base_domain": settings.sites_base_domain, "provider": settings.sites_provider, "grace_days": settings.sites_grace_days,
            "enquiry_retention_days": settings.sites_enquiry_retention_days, "pricing": PRICING_REFERENCE}


# ------------------------------------------------------------------------------------------------------------------ lookup
def get_by_tenant(db: Session, tenant_id: uuid.UUID) -> Site | None:
    return db.scalar(select(Site).where(Site.tenant_id == tenant_id))


def get(db: Session, site_id: uuid.UUID) -> Site:
    s = db.get(Site, site_id)
    if s is None:
        raise SiteError(404, "not_found", "Website not found.")
    return s


def hosted_domain(db: Session, site: Site) -> SiteDomain | None:
    return db.scalar(select(SiteDomain).where(SiteDomain.site_id == site.id, SiteDomain.domain_type == "hosted"))


def host_of(site: Site) -> str:
    return rules.hostname_for(site.site_slug, settings.sites_base_domain)


def slug_availability(db: Session, slug: str, tenant_id: uuid.UUID | None) -> str | None:
    """Why a site name cannot be used, or None. Checks the rules, existing sites and hostnames, and the 90-day quarantine (the business that released a name may take it back)."""
    p = rules.slug_problem(slug)
    if p:
        return p
    other = db.scalar(select(Site).where(Site.site_slug == slug))
    if other is not None and other.tenant_id != tenant_id:
        return "That name is already used by another website."
    if db.scalar(select(SiteDomain.id).where(SiteDomain.hostname == rules.hostname_for(slug, settings.sites_base_domain), SiteDomain.tenant_id != tenant_id)):
        return "That name is already used by another website."
    q = db.scalar(select(SiteSlugQuarantine).where(SiteSlugQuarantine.slug == slug))
    if q is not None and q.release_until > utcnow() and q.former_tenant_id != tenant_id:
        return f"That name was recently released and is held until {q.release_until.date().isoformat()}."
    return None


def _quarantine(db: Session, slug: str, tenant_id: uuid.UUID | None, reason: str) -> None:
    now = utcnow()
    row = db.scalar(select(SiteSlugQuarantine).where(SiteSlugQuarantine.slug == slug))
    until = now + timedelta(days=rules.QUARANTINE_DAYS)
    if row is None:
        db.add(SiteSlugQuarantine(slug=slug, former_tenant_id=tenant_id, released_at=now, release_until=until, reason=reason))
    else:
        row.former_tenant_id, row.released_at, row.release_until, row.reason = tenant_id, now, until, reason


def suggest_available_slug(db: Session, name: str, tenant_id: uuid.UUID) -> str:
    base = rules.suggest_slug(name)
    for i in range(0, 50):
        cand = base if i == 0 else f"{base[:rules.SLUG_MAX - len(str(i + 1)) - 1].strip('-')}-{i + 1}"
        if slug_availability(db, cand, tenant_id) is None:
            return cand
    return f"{base[:30].strip('-')}-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------------------------------------------------------ assets as the renderer needs them
def _assets(db: Session, site: Site, ids: set[str], with_data: bool) -> dict[str, render.Asset]:
    out: dict[str, render.Asset] = {}
    if not ids:
        return out
    q = select(SiteAsset).where(SiteAsset.site_id == site.id, SiteAsset.id.in_([uuid.UUID(i) for i in ids]))
    for a in db.scalars(q):
        out[str(a.id)] = render.Asset(id=str(a.id), sha256=a.sha256, width=a.width, height=a.height, alt=a.alt_text, data=bytes(a.data) if with_data else None)
    return out


def asset_ids(db: Session, site: Site) -> set[str]:
    return {str(i) for i in db.scalars(select(SiteAsset.id).where(SiteAsset.site_id == site.id))}


def asset_alts(db: Session, site: Site) -> dict[str, dict]:
    return {str(a.id): {"alt_text": a.alt_text} for a in db.scalars(select(SiteAsset).where(SiteAsset.site_id == site.id))}


# ------------------------------------------------------------------------------------------------------------------ create and edit
def _check_commercial_input(status: str, reason: str | None, billing_period: str | None, paid_until: date | None) -> None:
    if status not in ("complimentary", "paid_offline", "expired", "suspended"):
        raise SiteError(422, "bad_status", "Choose complimentary, paid (recorded offline), expired or suspended.")
    if status in ("complimentary", "expired", "suspended") and len((reason or "").strip()) < 5:
        raise SiteError(422, "reason_required", "Write a short reason (at least 5 characters). It is recorded in the audit log.")
    if status == "paid_offline" and not (billing_period in ("monthly", "annual") and paid_until):
        raise SiteError(422, "payment_details_required", "For a paid website choose monthly or annual and give the date it is paid until.")
    if billing_period not in (None, "", "monthly", "annual"):
        raise SiteError(422, "bad_period", "Billing period must be monthly or annual.")


def _business_facts(db: Session, tenant: Tenant) -> dict:
    loc = db.scalar(select(Location).where(Location.tenant_id == tenant.id, Location.is_active.is_(True)).order_by(Location.created_at).limit(1))
    return {"name": tenant.name, "category": tenant.category, "city": (loc.city if loc else None) or None, "phone": (loc.phone if loc and loc.phone else tenant.phone),
            "email": tenant.email, "address": ", ".join(x for x in ((loc.address_line if loc else None) or tenant.address, loc.city if loc else None) if x) or None,
            "review_url": loc.review_url if loc else None, "maps_url": None, "whatsapp": None}


def create_site(db: Session, *, admin, tenant: Tenant, template_key: str | None, slug: str | None, commercial_status: str, commercial_reason: str | None,
                billing_period: str | None, paid_until: date | None, ip: str | None = None) -> Site:
    require_enabled()
    if not tenant.is_active:
        raise SiteError(409, "tenant_suspended", "This business is suspended.")
    if get_by_tenant(db, tenant.id) is not None:
        raise SiteError(409, "already_exists", "This business already has a website.")
    if commercial_status not in ("complimentary", "paid_offline"):
        raise SiteError(422, "bad_status", "A new website starts as complimentary (with a reason) or paid (recorded offline). It is never free by default.")
    _check_commercial_input(commercial_status, commercial_reason, billing_period, paid_until)
    facts = _business_facts(db, tenant)
    key = template_key or C.suggest_template(tenant.category)
    if key not in C.TEMPLATES:
        raise SiteError(422, "bad_template", "Unknown template.")
    slug = slug or suggest_available_slug(db, tenant.name, tenant.id)
    problem = slug_availability(db, slug, tenant.id)
    if problem:
        raise SiteError(409 if "already" in problem or "held" in problem else 422, "bad_slug", problem)
    draft = C.default_content(key, facts)
    clean, errs = CT.validate_content(draft, key, set())
    if errs:  # a business record whose existing values are not valid website values (for example an unusual phone format): keep the page usable and let the editor show the problem
        for e in errs:
            _blank_path(draft, e["path"])
        clean, errs = CT.validate_content(draft, key, set())
    now = utcnow()
    site = Site(tenant_id=tenant.id, site_slug=slug, template_key=key, template_version=C.TEMPLATE_VERSION, status="draft", draft_content=clean, draft_version=1,
                commercial_status=commercial_status, commercial_reason=(commercial_reason or "").strip() or None, billing_period=billing_period or None, paid_until=paid_until,
                commercial_updated_by=admin.id, commercial_updated_at=now, created_by=admin.id, updated_by=admin.id)
    db.add(site)
    db.flush()
    db.add(SiteDomain(site_id=site.id, tenant_id=tenant.id, hostname=host_of(site), domain_type="hosted", status="active", is_primary=True, verification={}))
    _quarantine_clear(db, slug, tenant.id)
    audit(db, action="admin.site_create", tenant_id=tenant.id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip,
          meta={"slug": slug, "template": key, "commercial_status": commercial_status, "reason": (commercial_reason or "")[:300] or None})
    return site


def _blank_path(doc: dict, path: str) -> None:
    """Empty the value a validation error points at (used only to repair starting content copied from an existing business record)."""
    cur, parts = doc, re.findall(r"[^.\[\]]+", path)
    try:
        for p in parts[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = parts[-1]
        if isinstance(cur, dict) and last in cur:
            cur[last] = ""
    except (KeyError, IndexError, ValueError, TypeError):
        pass


def _quarantine_clear(db: Session, slug: str, tenant_id: uuid.UUID) -> None:
    db.execute(delete(SiteSlugQuarantine).where(SiteSlugQuarantine.slug == slug, SiteSlugQuarantine.former_tenant_id == tenant_id))


def save_content(db: Session, *, admin, site: Site, content: dict, base_version: int, ip: str | None = None) -> Site:
    """Save the draft. `base_version` is the draft_version the editor started from: a stale editor (another administrator saved meanwhile) gets 409 instead of overwriting."""
    require_enabled()
    if base_version != site.draft_version:
        raise SiteError(409, "version_conflict", "Someone else changed this website since you opened it. Reload to see their changes.", current_version=site.draft_version)
    clean, errs = CT.validate_content(content, site.template_key, asset_ids(db, site))
    if errs:
        raise SiteError(422, "invalid_content", "Some fields need attention.", errors=errs)
    site.draft_content, site.draft_version, site.updated_by = clean, site.draft_version + 1, admin.id
    audit(db, action="admin.site_edit", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"draft_version": site.draft_version, "sections": len(clean["sections"])})
    return site


def change_template(db: Session, *, admin, site: Site, template_key: str, ip: str | None = None) -> Site:
    """Switch the template of a DRAFT: the business details, button, search text and image library stay; sections of the same type keep their text; the rest start from the new template."""
    require_enabled()
    if template_key not in C.TEMPLATES:
        raise SiteError(422, "bad_template", "Unknown template.")
    if site.status == "published":
        raise SiteError(409, "unpublish_first", "Unpublish the website before changing its template.")
    old = site.draft_content
    fresh = C.default_content(template_key, {"name": old["business"]["name"], "city": old["business"]["city"]})
    kept: dict[str, dict] = {}
    for s in old["sections"]:
        kept.setdefault(s["type"], s)
    for s in fresh["sections"]:
        if s["type"] in kept:
            s["data"], s["enabled"] = kept[s["type"]]["data"], kept[s["type"]]["enabled"]
    fresh["business"], fresh["seo"] = old["business"], old["seo"]
    fresh["cta"], fresh["theme"] = old["cta"], old["theme"]
    clean, errs = CT.validate_content(fresh, template_key, asset_ids(db, site))
    if errs:
        raise SiteError(422, "invalid_content", "The content could not be moved to that template.", errors=errs)
    site.template_key, site.template_version, site.draft_content = template_key, C.TEMPLATE_VERSION, clean
    site.draft_version, site.updated_by = site.draft_version + 1, admin.id
    audit(db, action="admin.site_template", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"template": template_key})
    return site


def change_slug(db: Session, *, admin, site: Site, new_slug: str, ip: str | None = None) -> Site:
    require_enabled()
    if site.status == "published":
        raise SiteError(409, "unpublish_first", "Unpublish the website before changing its address.")
    if new_slug == site.site_slug:
        return site
    problem = slug_availability(db, new_slug, site.tenant_id)
    if problem:
        raise SiteError(409 if "already" in problem or "held" in problem else 422, "bad_slug", problem)
    old = site.site_slug
    _quarantine(db, old, site.tenant_id, "renamed")
    site.site_slug, site.updated_by = new_slug, admin.id
    d = hosted_domain(db, site)
    if d is not None:
        d.hostname = host_of(site)
    _quarantine_clear(db, new_slug, site.tenant_id)
    audit(db, action="admin.site_slug", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"from": old, "to": new_slug})
    return site


# ------------------------------------------------------------------------------------------------------------------ images
def upload_asset(db: Session, *, admin, site: Site, raw: bytes, kind: str, alt_text: str, ip: str | None = None) -> tuple[SiteAsset, bool]:
    """(asset, created). The same picture uploaded twice returns the existing one."""
    require_enabled()
    try:
        p = media.process_image(raw, kind)
    except media.MediaError as exc:
        raise SiteError(exc.status, exc.code, str(exc))
    existing = db.scalar(select(SiteAsset).where(SiteAsset.site_id == site.id, SiteAsset.sha256 == p.sha256))
    if existing is not None:
        return existing, False
    n, size = db.execute(select(func.count(), func.coalesce(func.sum(SiteAsset.size_bytes), 0)).where(SiteAsset.site_id == site.id)).one()
    if n >= media.MAX_ASSETS_PER_SITE:
        raise SiteError(409, "too_many_images", f"A website can have up to {media.MAX_ASSETS_PER_SITE} images. Remove one first.")
    if size + len(p.data) > media.MAX_SITE_BYTES:
        raise SiteError(409, "storage_full", "This website's image storage is full. Remove an image first.")
    alt = _INVISIBLE.sub("", alt_text or "").strip()[:200]
    a = SiteAsset(site_id=site.id, tenant_id=site.tenant_id, kind=kind, content_type=p.content_type, size_bytes=len(p.data), width=p.width, height=p.height, sha256=p.sha256, alt_text=alt,
                  sort_order=int(n), storage_key=p.storage_key, data=p.data)
    db.add(a)
    db.flush()
    audit(db, action="admin.site_asset_add", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site_asset", entity_id=a.id, ip=ip,
          meta={"kind": kind, "bytes": len(p.data), "size": f"{p.width}x{p.height}", "sha16": p.sha256[:16]})
    return a, True


def get_asset(db: Session, site: Site, asset_id: uuid.UUID) -> SiteAsset:
    a = db.scalar(select(SiteAsset).where(SiteAsset.id == asset_id, SiteAsset.site_id == site.id))  # scoped by the site: another business's image id is simply "not found"
    if a is None:
        raise SiteError(404, "not_found", "Image not found.")
    return a


def update_asset(db: Session, *, admin, site: Site, asset_id: uuid.UUID, alt_text: str | None, sort_order: int | None, ip: str | None = None) -> SiteAsset:
    a = get_asset(db, site, asset_id)
    if alt_text is not None:
        a.alt_text = _INVISIBLE.sub("", alt_text).strip()[:200]
    if sort_order is not None:
        a.sort_order = max(0, min(sort_order, 1000))
    audit(db, action="admin.site_asset_edit", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site_asset", entity_id=a.id, ip=ip, meta={"alt": alt_text is not None, "order": sort_order is not None})
    return a


def _strip_asset(x, aid: str):
    if isinstance(x, dict):
        return {k: (None if k in ("image", "logo", "og_image") and v == aid else _strip_asset(v, aid)) for k, v in x.items()}
    if isinstance(x, list):
        return [_strip_asset(i, aid) for i in x if not (isinstance(i, dict) and i.get("asset") == aid)]
    return x


def delete_asset(db: Session, *, admin, site: Site, asset_id: uuid.UUID, ip: str | None = None) -> None:
    """Remove an image from the library and from the DRAFT. The published copy keeps working until the next publish."""
    a = get_asset(db, site, asset_id)
    site.draft_content = _strip_asset(site.draft_content, str(a.id))
    site.draft_version += 1
    db.delete(a)
    audit(db, action="admin.site_asset_delete", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site_asset", entity_id=asset_id, ip=ip, meta={"sha16": a.sha256[:16]})


# ------------------------------------------------------------------------------------------------------------------ preview and readiness
def preview_html(db: Session, site: Site) -> str:
    clean, errs = CT.validate_content(site.draft_content, site.template_key, asset_ids(db, site))
    assets = _assets(db, site, CT.referenced_assets(clean), True)
    files = render.build_site(clean, site.template_key, host=host_of(site), assets=assets, retention_days=settings.sites_enquiry_retention_days, preview=True)
    return files["index.html"].decode()


def commercial_blockers(site: Site, tenant: Tenant) -> list[dict]:
    out = []
    if site.commercial_status not in ("complimentary", "paid_offline"):
        out.append({"path": "commercial", "message": "Hosting is " + site.commercial_status.replace("_", " ") + ". Record it as complimentary or paid before publishing."})
    if site.status == "suspended":
        out.append({"path": "status", "message": "This website is suspended. Resume it first."})
    if not tenant.is_active:
        out.append({"path": "business", "message": "The business is suspended."})
    return out


def readiness(db: Session, site: Site) -> list[dict]:
    tenant = db.get(Tenant, site.tenant_id)
    clean, errs = CT.validate_content(site.draft_content, site.template_key, asset_ids(db, site))
    return commercial_blockers(site, tenant) + [{"path": e["path"], "message": e["message"]} for e in errs] + CT.publish_blockers(clean, site.template_key, asset_alts(db, site))


# ------------------------------------------------------------------------------------------------------------------ publish, unpublish, suspend, rollback
def _provider() -> hosting.HostingProvider:
    p = hosting.get_hosting_provider()
    if not p.configured():
        raise SiteError(409, "hosting_not_configured", "Website hosting is not configured on this server.")
    return p


def publish(db: Session, *, admin, site: Site, note: str | None = None, ip: str | None = None) -> Site:
    require_enabled()
    blockers = readiness(db, site)
    if blockers:
        raise SiteError(422, "not_ready", "This website is not ready to publish.", blockers=blockers)
    provider = _provider()
    clean, _ = CT.validate_content(site.draft_content, site.template_key, asset_ids(db, site))
    host = host_of(site)
    version = max(site.live_version, site.publish_counter) + 1
    site.publish_counter, site.publish_state, site.publish_attempted_at, site.publish_error = version, "publishing", utcnow(), None
    db.commit()  # the attempt is on record before anything is uploaded
    try:
        assets = _assets(db, site, CT.referenced_assets({"business": clean["business"], "seo": clean["seo"], "sections": [s for s in clean["sections"] if s["enabled"]]}), True)
        files = provider.build_site(clean, site.template_key, host=host, assets=assets, retention_days=settings.sites_enquiry_retention_days)
        result = provider.publish_site(str(site.id), host, files, version)
    except Exception as exc:  # noqa: BLE001 - whatever failed, the previous version is still live
        db.rollback()
        site = db.get(Site, site.id)
        message = str(exc) if isinstance(exc, hosting.HostingError) else "The website could not be published."
        code = exc.code if isinstance(exc, hosting.HostingError) else "publish_failed"
        site.publish_state, site.publish_error = "failed", message[:300]
        audit(db, action="admin.site_publish_failed", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"version": version, "code": code})
        db.commit()
        log.warning("site publish failed: %s", code)
        raise SiteError(502, "publish_failed", message + " The website that was already live is unchanged.", retryable=bool(getattr(exc, "retryable", True)), live_version=site.live_version)
    n = (db.scalar(select(func.max(SiteRevision.revision)).where(SiteRevision.site_id == site.id)) or 0) + 1
    now = utcnow()
    site.published_content, site.published_at, site.published_by = clean, now, admin.id
    site.live_version, site.status, site.publish_state, site.publish_error = version, "published", "idle", None
    db.add(SiteRevision(site_id=site.id, tenant_id=site.tenant_id, revision=n, hosting_version=version, content=clean, template_key=site.template_key, template_version=site.template_version,
                        editor=admin.id, note=(note or "")[:200] or None, created_at=now))
    audit(db, action="admin.site_publish", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip,
          meta={"version": version, "revision": n, "files": result.files, "bytes": result.bytes, "note": (note or "")[:200] or None})
    return site


def _host_call(fn, what: str) -> None:
    try:
        fn()
    except hosting.HostingError as exc:
        raise SiteError(502, "hosting_failed", f"{what} {exc}", retryable=exc.retryable)


def unpublish(db: Session, *, admin, site: Site, ip: str | None = None) -> Site:
    require_enabled()
    if site.status != "published":
        raise SiteError(409, "not_published", "This website is not published.")
    provider = _provider()
    _host_call(lambda: provider.unpublish_site(str(site.id), host_of(site)), "The website could not be taken offline.")
    site.status, site.updated_by = "unpublished", admin.id
    audit(db, action="admin.site_unpublish", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"version": site.live_version})
    return site


def suspend(db: Session, *, admin, site: Site, reason: str, ip: str | None = None, system: bool = False) -> Site:
    """Take a website out of public view without losing anything. The hostname answers with a 'temporarily unavailable' page; content and history stay."""
    require_enabled()
    if len((reason or "").strip()) < 5 and not system:
        raise SiteError(422, "reason_required", "Write a short reason (at least 5 characters).")
    if site.status == "suspended":
        return site
    if site.status == "published":
        provider = _provider()
        _host_call(lambda: provider.set_status(str(site.id), host_of(site), site.live_version, "suspended"), "The website could not be suspended.")
    site.status = "suspended"
    if admin is not None:
        site.updated_by = admin.id
    audit(db, action="admin.site_suspend" if not system else "system.site_suspend", tenant_id=site.tenant_id, user_id=admin.id if admin else None, entity_type="site", entity_id=site.id, ip=ip,
          meta={"reason": (reason or "")[:300]})
    return site


def unsuspend(db: Session, *, admin, site: Site, ip: str | None = None) -> Site:
    require_enabled()
    if site.status != "suspended":
        raise SiteError(409, "not_suspended", "This website is not suspended.")
    tenant = db.get(Tenant, site.tenant_id)
    if site.commercial_status not in ("complimentary", "paid_offline") or not tenant.is_active:
        raise SiteError(409, "commercial_not_active", "Record hosting as complimentary or paid (and make sure the business is active) before resuming.")
    provider = _provider()
    live = provider.get_publish_status(str(site.id), host_of(site))
    if live and live.get("status") == "suspended":
        _host_call(lambda: provider.set_status(str(site.id), host_of(site), live["version"], "published"), "The website could not be resumed.")
        site.status = "published"
    else:
        site.status = "unpublished"
    site.updated_by = admin.id
    audit(db, action="admin.site_unsuspend", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"now": site.status})
    return site


def rollback(db: Session, *, admin, site: Site, revision: int, ip: str | None = None) -> Site:
    """Publish the content of an earlier successful publish again (as a new revision)."""
    require_enabled()
    rev = db.scalar(select(SiteRevision).where(SiteRevision.site_id == site.id, SiteRevision.revision == revision))
    if rev is None:
        raise SiteError(404, "not_found", "That revision does not exist.")
    clean, errs = CT.validate_content(rev.content, rev.template_key, asset_ids(db, site))
    if errs:
        raise SiteError(422, "invalid_content", "That revision uses an image that has since been removed. Upload it again, or restore the content by hand.", errors=errs)
    site.template_key, site.template_version, site.draft_content, site.draft_version = rev.template_key, rev.template_version, clean, site.draft_version + 1
    audit(db, action="admin.site_rollback", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"to_revision": revision})
    return publish(db, admin=admin, site=site, note=f"Rollback to revision {revision}", ip=ip)


def delete_site(db: Session, *, admin, site: Site, ip: str | None = None) -> None:
    """Remove a website entirely (it must be unpublished or never published). Its name is held for 90 days."""
    require_enabled()
    if site.status == "published":
        raise SiteError(409, "unpublish_first", "Unpublish the website before deleting it.")
    _remove_hosting(db, site)
    slug, tid, sid = site.site_slug, site.tenant_id, site.id
    _quarantine(db, slug, tid, "deleted")
    db.delete(site)
    audit(db, action="admin.site_delete", tenant_id=tid, user_id=admin.id, entity_type="site", entity_id=sid, ip=ip, meta={"slug": slug})


def _remove_hosting(db: Session, site: Site) -> None:
    if site.live_version <= 0 and site.publish_counter <= 0:
        return
    provider = hosting.get_hosting_provider()
    if not provider.configured():
        raise SiteError(409, "hosting_not_configured", "This website was published, but hosting is not configured on this server, so its files cannot be removed. Configure hosting and try again.")
    hosts = [d.hostname for d in db.scalars(select(SiteDomain).where(SiteDomain.site_id == site.id))]
    _host_call(lambda: provider.delete_site(str(site.id), hosts), "The website's files could not be removed.")


# ------------------------------------------------------------------------------------------------------------------ commercial status
def set_commercial(db: Session, *, admin, site: Site, status: str, reason: str | None, billing_period: str | None, paid_until: date | None, ip: str | None = None) -> Site:
    """Record hosting status by hand. Every change is audited with who, what it was, what it is now, and why. 'expired' starts the grace period; 'suspended' takes the site out of public view.
    Moving back to complimentary or paid does NOT put a suspended site back live by itself: use Resume."""
    require_enabled()
    _check_commercial_input(status, reason, billing_period, paid_until)
    before = {"status": site.commercial_status, "paid_until": site.paid_until.isoformat() if site.paid_until else None, "billing_period": site.billing_period}
    now = utcnow()
    site.commercial_status, site.commercial_reason = status, (reason or "").strip()[:300] or None
    site.billing_period = billing_period or site.billing_period
    site.paid_until = paid_until if status == "paid_offline" else site.paid_until
    site.grace_until = (now + timedelta(days=settings.sites_grace_days)) if status == "expired" else None
    site.commercial_updated_by, site.commercial_updated_at = admin.id if admin else None, now
    audit(db, action="admin.site_commercial", tenant_id=site.tenant_id, user_id=admin.id if admin else None, entity_type="site", entity_id=site.id, ip=ip,
          meta={"from": before, "to": status, "reason": (reason or "")[:300] or None, "paid_until": paid_until.isoformat() if paid_until else None, "grace_until": site.grace_until.isoformat() if site.grace_until else None})
    if status == "suspended" and site.status != "suspended":
        suspend(db, admin=admin, site=site, reason=reason or "hosting suspended", ip=ip)
    return site


def enforce_commercial(db: Session, now: datetime | None = None) -> dict:
    """The daily check: paid-until dates that have passed become 'expired' with a grace period; a site whose grace period has ended, or whose business is suspended, is suspended. Never deletes anything."""
    now = now or utcnow()
    out = {"expired": 0, "suspended": 0, "errors": 0}
    if not settings.sites_enabled:
        return out
    for s in db.scalars(select(Site).where(Site.commercial_status == "paid_offline", Site.paid_until.is_not(None), Site.paid_until < now.date())):
        s.commercial_status, s.commercial_reason, s.grace_until = "expired", "Paid-until date passed", now + timedelta(days=settings.sites_grace_days)
        audit(db, action="system.site_expired", tenant_id=s.tenant_id, entity_type="site", entity_id=s.id, meta={"paid_until": s.paid_until.isoformat(), "grace_until": s.grace_until.isoformat()})
        out["expired"] += 1
    db.flush()
    due = db.scalars(select(Site).where(Site.status == "published")).all()
    for s in due:
        tenant = db.get(Tenant, s.tenant_id)
        why = None
        if s.commercial_status == "expired" and s.grace_until and s.grace_until <= now:
            why = "Hosting expired and the grace period has ended"
        elif s.commercial_status == "suspended":
            why = "Hosting suspended"
        elif tenant is not None and not tenant.is_active:
            why = "The business is suspended"
        if why:
            try:
                suspend(db, admin=None, site=s, reason=why, system=True)
                out["suspended"] += 1
            except SiteError:
                out["errors"] += 1
                log.warning("could not suspend a lapsed site")
    return out


# ------------------------------------------------------------------------------------------------------------------ enquiries
def _ip_hash(ip: str | None) -> str | None:
    return hmac.new(settings.secret_key.encode(), (ip or "").encode(), hashlib.sha256).hexdigest()[:32] if ip else None


def _live_site_for_host(db: Session, host: str) -> Site | None:
    slug = rules.slug_from_host(host, settings.sites_base_domain)
    if not slug:
        return None
    d = db.scalar(select(SiteDomain).where(SiteDomain.hostname == rules.hostname_for(slug, settings.sites_base_domain), SiteDomain.status == "active"))
    s = db.get(Site, d.site_id) if d else None
    if s is None or s.status != "published" or s.commercial_status not in ("complimentary", "paid_offline"):
        return None
    t = db.get(Tenant, s.tenant_id)
    return s if t is not None and t.is_active else None


class Notifier:
    def new_enquiry(self, site: Site, enquiry: SiteEnquiry) -> None:  # pragma: no cover - interface
        ...


class NullNotifier(Notifier):
    """Default: no email is sent. Enquiries are read in the admin inbox."""

    def new_enquiry(self, site, enquiry):
        return None


class SmtpNotifier(Notifier):
    """Optional. NOT enabled by default: the shared mailbox has daily sending limits and a Gmail From address is a poor sender for other businesses' mail. Review before use."""

    def new_enquiry(self, site, enquiry):
        from app.services.mailer import send_email

        to = (site.draft_content or {}).get("business", {}).get("email")
        if to:
            send_email(to, "New website enquiry", f"{enquiry.name} sent an enquiry through your website. Open the FlowQR admin to read it.")


def get_notifier() -> Notifier:
    return SmtpNotifier() if settings.sites_enquiry_notifier == "smtp" else NullNotifier()


def create_enquiry(db: Session, *, host: str, payload: dict, ip: str | None) -> bool:
    """A visitor's enquiry, from the hosting Worker. Unknown, unpublished, suspended and unpaid sites all answer the same 404. A filled honeypot is answered as a success and stores nothing."""
    if not settings.sites_enabled:
        raise SiteError(404, "not_found", "Not found.")
    site = _live_site_for_host(db, host)
    if site is None:
        raise SiteError(404, "not_found", "Not found.")
    iph = _ip_hash(ip)
    if not hit(f"site-enq-ip:{site.id}:{iph or 'x'}", 5, 3600) or not hit(f"site-enq-site:{site.id}", 100, 86400):
        raise SiteError(429, "rate_limited", "Too many enquiries. Please try again later.")
    if (payload.get("website") or "").strip():
        return True
    if not payload.get("consent"):
        raise SiteError(422, "consent_required", "Please tick the box to agree before sending.")
    name = _INVISIBLE.sub("", str(payload.get("name") or "")).strip()
    message = _INVISIBLE.sub("", str(payload.get("message") or "")).replace("\r\n", "\n").strip()
    email = _INVISIBLE.sub("", str(payload.get("email") or "")).strip().lower()
    phone_raw = _INVISIBLE.sub("", str(payload.get("phone") or "")).strip()
    if not (2 <= len(name) <= 120) or not (3 <= len(message) <= 1500):
        raise SiteError(422, "invalid", "Please enter your name and a message.")
    phone = None
    if phone_raw:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError:
            raise SiteError(422, "invalid_phone", "Enter a valid 10-digit mobile number.")
    if email and not registration.normalize_email(email):
        raise SiteError(422, "invalid_email", "Enter a valid email address.")
    if not (phone or email):
        raise SiteError(422, "contact_required", "Please give a phone number or an email so the business can reply.")
    e = SiteEnquiry(site_id=site.id, tenant_id=site.tenant_id, name=name, phone=phone, email=email or None, message=message, consent_at=utcnow(), status="new", ip_hash=iph)
    db.add(e)
    db.flush()
    if payload.get("whatsapp_ok") and settings.whatsapp_enabled:
        try:  # the visitor's own tick: record their WhatsApp consent and schedule the helper's messages. Never allowed to lose the enquiry.
            with db.begin_nested():
                from app.services.whatsapp import automations as wa_automations

                wa_automations.on_enquiry(db, site.tenant_id, e, True)
        except Exception:  # noqa: BLE001
            log.warning("WhatsApp follow-up for an enquiry could not be scheduled")
    try:
        get_notifier().new_enquiry(site, e)
    except Exception:  # noqa: BLE001 - a notification problem must never lose the enquiry
        log.warning("enquiry notification failed")
    return True


def list_enquiries(db: Session, site: Site, status: str | None, limit: int, offset: int) -> tuple[int, list[SiteEnquiry]]:
    q = select(SiteEnquiry).where(SiteEnquiry.site_id == site.id)
    if status:
        q = q.where(SiteEnquiry.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    return total, list(db.scalars(q.order_by(SiteEnquiry.created_at.desc()).limit(limit).offset(offset)))


def set_enquiry_status(db: Session, *, admin, site: Site, enquiry_id: uuid.UUID, status: str, ip: str | None = None) -> SiteEnquiry:
    e = db.scalar(select(SiteEnquiry).where(SiteEnquiry.id == enquiry_id, SiteEnquiry.site_id == site.id))
    if e is None:
        raise SiteError(404, "not_found", "Enquiry not found.")
    if status not in ("new", "contacted", "resolved", "spam"):
        raise SiteError(422, "bad_status", "Choose new, contacted, resolved or spam.")
    now = utcnow()
    e.status, e.handled_by = status, admin.id
    if status == "contacted":
        e.contacted_at = now
    if status == "resolved":
        e.resolved_at = now
    audit(db, action="admin.site_enquiry_status", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site_enquiry", entity_id=e.id, ip=ip, meta={"status": status})
    return e


def _csv_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # a spreadsheet must never run an enquiry as a formula


def enquiries_csv(db: Session, *, admin, site: Site, ip: str | None = None) -> str:
    rows = db.scalars(select(SiteEnquiry).where(SiteEnquiry.site_id == site.id).order_by(SiteEnquiry.created_at)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["received", "status", "name", "phone", "email", "message", "consent_given"])
    for e in rows:
        w.writerow([e.created_at.isoformat(), e.status, _csv_cell(e.name), _csv_cell(e.phone), _csv_cell(e.email), _csv_cell(e.message), e.consent_at.isoformat()])
    audit(db, action="admin.site_enquiries_export", tenant_id=site.tenant_id, user_id=admin.id, entity_type="site", entity_id=site.id, ip=ip, meta={"rows": len(rows)})
    return buf.getvalue()


def purge_old_enquiries(db: Session, now: datetime | None = None) -> int:
    """Delete enquiries older than SITES_ENQUIRY_RETENTION_DAYS (the visitor was told this period on the privacy page). Returns how many."""
    cutoff = (now or utcnow()) - timedelta(days=settings.sites_enquiry_retention_days)
    res = db.execute(delete(SiteEnquiry).where(SiteEnquiry.created_at < cutoff))
    return res.rowcount or 0


# ------------------------------------------------------------------------------------------------------------------ account export and tenant deletion
def on_tenant_delete(db: Session, tenant_id: uuid.UUID) -> None:
    """Called by account.delete_tenant BEFORE the business is deleted. Takes the website offline, removes its files, and holds the name for 90 days. If the hosting provider cannot do it,
    this raises and the deletion does not proceed (the daily job retries): a deleted business must not stay publicly visible."""
    site = get_by_tenant(db, tenant_id)
    if site is None:
        return
    _remove_hosting(db, site)
    _quarantine(db, site.site_slug, tenant_id, "business_deleted")


def export_files(db: Session, tenant_id: uuid.UUID) -> list[tuple[str, bytes]]:
    """The business's own uploaded images, for the data export ZIP."""
    site = get_by_tenant(db, tenant_id)
    if site is None:
        return []
    return [(f"site_files/{a.id}.webp", bytes(a.data)) for a in db.scalars(select(SiteAsset).where(SiteAsset.site_id == site.id).order_by(SiteAsset.created_at))]


# ------------------------------------------------------------------------------------------------------------------ output shapes
def serialize(db: Session, site: Site, *, full: bool = True) -> dict:
    tenant = db.get(Tenant, site.tenant_id)
    host = host_of(site)
    out = {"id": site.id, "tenant_id": site.tenant_id, "site_slug": site.site_slug, "hostname": host, "url": f"https://{host}/", "template_key": site.template_key,
           "template_version": site.template_version, "status": site.status, "draft_version": site.draft_version, "live_version": site.live_version, "published_at": site.published_at,
           "publish_state": site.publish_state, "publish_error": site.publish_error, "publish_attempted_at": site.publish_attempted_at,
           "commercial": {"status": site.commercial_status, "reason": site.commercial_reason, "billing_period": site.billing_period, "paid_until": site.paid_until, "grace_until": site.grace_until,
                          "updated_at": site.commercial_updated_at},
           "business_active": bool(tenant and tenant.is_active), "created_at": site.created_at, "updated_at": site.updated_at,
           "assets": [{"id": a.id, "kind": a.kind, "width": a.width, "height": a.height, "size_bytes": a.size_bytes, "alt_text": a.alt_text, "sort_order": a.sort_order}
                      for a in db.scalars(select(SiteAsset).where(SiteAsset.site_id == site.id).order_by(SiteAsset.sort_order, SiteAsset.created_at))],
           "domains": [{"id": d.id, "hostname": d.hostname, "domain_type": d.domain_type, "status": d.status, "is_primary": d.is_primary}
                       for d in db.scalars(select(SiteDomain).where(SiteDomain.site_id == site.id))],
           "enquiries": {"new": db.scalar(select(func.count()).select_from(SiteEnquiry).where(SiteEnquiry.site_id == site.id, SiteEnquiry.status == "new")) or 0,
                         "total": db.scalar(select(func.count()).select_from(SiteEnquiry).where(SiteEnquiry.site_id == site.id)) or 0},
           "revisions": [{"revision": r.revision, "hosting_version": r.hosting_version, "created_at": r.created_at, "note": r.note}
                         for r in db.scalars(select(SiteRevision).where(SiteRevision.site_id == site.id).order_by(SiteRevision.revision.desc()).limit(20))]}
    if full:
        out["draft_content"] = site.draft_content
        out["readiness"] = readiness(db, site)
        out["edits_this_month"] = db.scalar(select(func.count()).select_from(SiteRevision).where(SiteRevision.site_id == site.id, SiteRevision.created_at >= utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0))) or 0
    return out
