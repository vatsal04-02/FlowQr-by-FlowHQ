"""Admin-managed businesses: a FlowQR administrator creates a business, its locations and its access, with no shopkeeper account.

Design rules (each tested in tests/test_admin_businesses.py):
  * A business is a `tenants` row. It never needed a user: owners are `memberships`, and an admin-created business simply has none (origin = 'admin'). No user, no password, no dummy login is created.
  * Cards, scans, NFC taps and the review page work from the tenant and its location alone; nothing here makes them depend on an account.
  * "Managed access": the business gets the Launch plan through a manual subscription (status `manual`, no trial clock, no billing provider, no payment). Launch's limits are the ones enforced everywhere
    (150 AI review writings and 150 AI replies a month, 1 team seat). An administrator can revoke it (the AI features stop; cards and the plain review page keep working) and restore it.
  * Every create, edit, agreement and claim is audited with the administrator's id. Tenant isolation is untouched: all of this runs behind the platform-admin check, which sets the RLS bypass
    for admin work only.
  * An offline agreement is recorded as what it is: an administrator's statement. It is never shown as the shopkeeper's own acceptance of the terms or a confirmation that they are 18 or older.
  * A claim invitation is optional, off by default, expires, can be revoked, adds the invited address to the registration allowlist with an audit entry, and works only while the business has no owner."""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, urlsplit

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_token, new_token
from app.models import AIGenerationLog, BillingPlan, Invitation, Location, Membership, QRCard, RegistrationAllowlist, Role, Subscription, Tenant, TenantAgreement, User
from app.models.base import utcnow
from app.services import billing as billing_svc
from app.services import cards as cards_svc
from app.services import registration
from app.services.ai_usage import month_start
from app.services.audit import audit
from app.services.mailer import send_email

MANAGED_PLAN = "starter"  # Launch
TERMS_VERSION = "2026-11-18.admin-offline.1"  # the version of the terms an administrator took the business through when recording an offline agreement
AGREEMENT_METHODS = ("phone", "in_person", "whatsapp", "paper", "other")
AGREEMENT_STATEMENT = ("Recorded by a FlowQR administrator on behalf of the business. This is NOT the shopkeeper personally accepting the terms and does NOT confirm that anyone is 18 or older.")
LIVE_CARD_STATUSES = (cards_svc.CardStatus.assigned, cards_svc.CardStatus.active)


class ProvisionError(Exception):
    """A refusal the API turns into an HTTP error. `detail` is JSON-safe."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "business"
    return f"{base}-{secrets.token_hex(3)}"


# ---------------------------------------------------------------------------------------------------------------------------------------------- duplicates
def norm_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def last10(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else None


def place_key(url: str | None) -> str | None:
    """A stable identity for the Google place behind a review link: the id in g.page/r/<id>/review, or the placeid / cid query value. None when there is nothing to compare."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    q = parse_qs(parts.query)
    for k in ("placeid", "place_id", "cid"):
        if q.get(k):
            return f"{k}:{q[k][0].lower()}"
    m = re.match(r"^/r/([A-Za-z0-9_-]{6,})", parts.path or "")
    if (parts.hostname or "").lower().endswith("g.page") and m:
        return f"gpage:{m.group(1).lower()}"
    return None


def find_duplicates(db: Session, *, name: str, city: str | None, phone: str | None, email: str | None, review_url: str | None, exclude_tenant_id: uuid.UUID | None = None) -> list[dict]:
    """Existing businesses that look like the one being created, with the reason for each match. Never decides anything: the caller shows them and asks the administrator."""
    found: dict[uuid.UUID, dict] = {}

    def hit(tenant: Tenant, reason: str) -> None:
        row = found.setdefault(tenant.id, {"id": str(tenant.id), "name": tenant.name, "city": None, "phone": tenant.phone, "origin": tenant.origin, "reasons": []})
        if reason not in row["reasons"]:
            row["reasons"].append(reason)

    def keep(q):
        return q.where(Tenant.id != exclude_tenant_id) if exclude_tenant_id else q

    n = norm_name(name)
    flat = func.regexp_replace(func.lower(Tenant.name), "[^a-z0-9]", "", "g")
    if n:
        for t in db.scalars(keep(select(Tenant).where(flat == n))):
            cities = {(l.city or "").strip().lower() for l in db.scalars(select(Location).where(Location.tenant_id == t.id))}
            same_city = bool(city) and (city or "").strip().lower() in cities
            hit(t, "Same name in the same city" if same_city else "Same name")
    p = last10(phone)
    if p:
        digits = func.regexp_replace(func.coalesce(Tenant.phone, ""), "[^0-9]", "", "g")
        for t in db.scalars(keep(select(Tenant).where(func.right(digits, 10) == p))):
            hit(t, "Same phone number")
        ldigits = func.regexp_replace(func.coalesce(Location.phone, ""), "[^0-9]", "", "g")
        for t in db.scalars(keep(select(Tenant).where(Tenant.id.in_(select(Location.tenant_id).where(func.right(ldigits, 10) == p))))):
            hit(t, "Same phone number")
    e = registration.normalize_email(email) if email else None
    if e:
        for t in db.scalars(keep(select(Tenant).where(func.lower(Tenant.email) == e))):
            hit(t, "Same email")
    key = place_key(review_url)
    if key:
        ident = key.split(":", 1)[1]
        for loc in db.scalars(select(Location).where(Location.review_url.ilike(f"%{ident}%"))):
            if place_key(loc.review_url) == key:
                t = db.get(Tenant, loc.tenant_id)
                if t and t.id != exclude_tenant_id:
                    hit(t, "Same Google place (review link)")
    for row in found.values():
        locs = db.scalars(select(Location).where(Location.tenant_id == uuid.UUID(row["id"])).limit(1)).all()
        row["city"] = locs[0].city if locs else None
    return sorted(found.values(), key=lambda r: (-len(r["reasons"]), r["name"].lower()))


# ---------------------------------------------------------------------------------------------------------------------------------------------- create
def grant_managed_access(db: Session, tenant: Tenant, *, by: uuid.UUID | None) -> Subscription:
    plan = db.get(BillingPlan, MANAGED_PLAN)
    if plan is None:
        raise ProvisionError(500, "plan_missing", "The Launch plan is not configured.")
    sub = Subscription(tenant_id=tenant.id, plan=MANAGED_PLAN, status="manual", currency="INR", source="manual")  # no trial dates, no provider, no payment, no renewal
    billing_svc.apply_plan(sub, plan)
    db.add(sub)
    billing_svc.log_event(db, tenant.id, "managed_access_granted", source="admin", to_status="manual", to_plan=MANAGED_PLAN, meta={"by": str(by) if by else None, "plan_name": plan.name})
    return sub


def record_agreement(db: Session, tenant: Tenant, *, by: uuid.UUID, method: str, note: str | None, now: datetime | None = None) -> TenantAgreement:
    if method not in AGREEMENT_METHODS:
        raise ProvisionError(422, "bad_method", "Choose how the agreement was recorded.")
    row = TenantAgreement(tenant_id=tenant.id, recorded_by=by, recorded_at=now or utcnow(), terms_version=TERMS_VERSION, method=method, note=(note or "").strip()[:300] or None,
                          statement=AGREEMENT_STATEMENT)
    db.add(row)
    db.flush()
    audit(db, action="admin.business_agreement_recorded", tenant_id=tenant.id, user_id=by, entity_type="tenant", entity_id=tenant.id,
          meta={"terms_version": TERMS_VERSION, "method": method, "personal_acceptance": False})
    return row


def create_business(db: Session, *, admin: User, data: dict, ip: str | None = None) -> tuple[Tenant, Location]:
    """One transaction: the business, its first location, its managed access, and (optionally) the offline agreement. No user, membership or password is created."""
    dups = find_duplicates(db, name=data["name"], city=data.get("city"), phone=data.get("phone"), email=data.get("email"), review_url=data.get("review_url"))
    reason = (data.get("duplicate_reason") or "").strip()
    if dups and not reason:
        raise ProvisionError(409, "duplicates_found", "A similar business already exists. Check the matches, then create anyway with a reason if this is really a different business.", matches=dups)
    t = Tenant(slug=slugify(data["name"]), name=data["name"], category=data.get("category"), contact_name=data.get("contact_name"), phone=data.get("phone"), email=data.get("email"),
               address=data.get("address"), website=data.get("website"), origin="admin", created_by=admin.id, updated_by=admin.id, onboarding_completed=True)
    db.add(t)
    db.flush()
    loc = Location(tenant_id=t.id, name=data.get("location_name") or data["name"], address_line=data.get("address"), city=data.get("city"), phone=data.get("phone"), review_url=data.get("review_url"),
                   review_url_source="manual")
    db.add(loc)
    grant_managed_access(db, t, by=admin.id)
    db.flush()
    audit(db, action="admin.business_create", tenant_id=t.id, user_id=admin.id, entity_type="tenant", entity_id=t.id, ip=ip,
          meta={"location_id": str(loc.id), "origin": "admin", "user_account_created": False, "duplicates_overridden": [str(d["id"]) for d in dups],
                **({"duplicate_reason": reason[:300]} if dups else {})})
    if data.get("agreement"):
        record_agreement(db, t, by=admin.id, method=data["agreement"]["method"], note=data["agreement"].get("note"))
    return t, loc


# ---------------------------------------------------------------------------------------------------------------------------------------------- managed access
def managed_state(sub: Subscription | None) -> str:
    """none | managed (active) | revoked | other (a business with its own trial or paid plan: not ours to change here)."""
    if sub is None:
        return "none"
    if sub.provider or sub.razorpay_subscription_id or sub.cashfree_subscription_id:
        return "other"
    if sub.source == "manual" and sub.status == "manual":
        return "managed"
    if sub.source == "manual" and sub.status == "expired":
        return "revoked"
    return "other"


def set_managed_access(db: Session, tenant: Tenant, *, revoke: bool, by: uuid.UUID, note: str) -> Subscription:
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant.id).with_for_update())
    state = managed_state(sub)
    if state in ("none", "other"):
        raise ProvisionError(409, "not_managed", "This business is not on managed access (it has its own trial or paid plan). Use the subscription controls instead.")
    if revoke and state == "revoked" or not revoke and state == "managed":
        return sub
    before = billing_svc.snapshot(sub)
    sub.status = "expired" if revoke else "manual"
    billing_svc.record_change(db, sub, before, source="admin", kind="managed_access_revoked" if revoke else "managed_access_restored", meta={"note": note[:300], "by": str(by)})
    audit(db, action="admin.managed_access_revoked" if revoke else "admin.managed_access_restored", tenant_id=tenant.id, user_id=by, entity_type="subscription", entity_id=sub.id, meta={"note": note[:300]})
    return sub


# ---------------------------------------------------------------------------------------------------------------------------------------------- optional claiming
def has_owner(db: Session, tenant_id: uuid.UUID) -> bool:
    return db.scalar(select(Membership.id).where(Membership.tenant_id == tenant_id, Membership.role == Role.owner).limit(1)) is not None


def whatsapp_url(phone: str | None, message: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    base = f"https://wa.me/{digits}" if 11 <= len(digits) <= 15 else "https://wa.me/"
    return f"{base}?text={quote(message)}"


def create_claim_invitation(db: Session, tenant: Tenant, *, admin: User, email: str, delivery: str, ip: str | None = None) -> dict:
    if not settings.claim_invitations_enabled:
        raise ProvisionError(409, "claims_disabled", "Claim invitations are switched off on this server. Cards and review pages do not need them.")
    if delivery not in ("email", "link"):
        raise ProvisionError(422, "bad_delivery", "Choose email or a copyable link.")
    if not tenant.is_active:
        raise ProvisionError(409, "tenant_suspended", "This business is suspended.")
    if has_owner(db, tenant.id):
        raise ProvisionError(409, "already_claimed", "This business already has an owner.")
    n = registration.normalize_email(email)
    if not n:
        raise ProvisionError(422, "bad_email", "Enter a valid email address.")
    now = utcnow()
    for old in db.scalars(select(Invitation).where(Invitation.tenant_id == tenant.id, Invitation.role == Role.owner, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))):
        old.revoked_at = now  # one open claim at a time
    token = new_token()
    inv = Invitation(tenant_id=tenant.id, email=n, role=Role.owner, token_hash=hash_token(token), invited_by=admin.id, location_ids=None, expires_at=now + timedelta(hours=settings.claim_invitation_ttl_hours))
    db.add(inv)
    db.flush()
    already = registration.is_listed(db, n)
    had_row = db.scalar(select(RegistrationAllowlist.id).where(RegistrationAllowlist.email == n)) is not None
    row = registration.add(db, n, note=f"Claim invitation for {tenant.name}"[:300], user_id=admin.id)  # without this a closed or allowlist-only registration would refuse the shopkeeper's sign-up
    if not had_row:
        inv.allowlist_entry_id = row.id  # THIS claim created the row: only such a row may be removed again when the claim is revoked
    audit(db, action="admin.allowlist_added_for_claim", tenant_id=tenant.id, user_id=admin.id, entity_type="registration_allowlist", entity_id=inv.id, ip=ip,
          meta={"email": n, "already_listed": already, "entry_created_by_this_claim": not had_row})
    audit(db, action="admin.claim_invitation_created", tenant_id=tenant.id, user_id=admin.id, entity_type="invitation", entity_id=inv.id, ip=ip,
          meta={"email": n, "delivery": delivery, "expires_at": inv.expires_at.isoformat()})
    link = f"{settings.frontend_url.rstrip('/')}/accept-invite?token={token}"
    message = f"Hello, FlowQR has set up {tenant.name} for you. If you would like to manage it yourself, create your free account here: {link}"
    out = {"invitation_id": inv.id, "email": n, "expires_at": inv.expires_at, "delivery": delivery, "email_sent": None, "link": None, "whatsapp_url": None}
    if delivery == "email":
        out["email_sent"] = send_email(n, f"Take over {tenant.name} on FlowQR", message)  # never claim delivery we cannot confirm
    else:
        out["link"], out["whatsapp_url"] = link, whatsapp_url(tenant.phone, message)  # shown once: only a hash of the token is stored
    return out


def allowlist_removal_check(db: Session, inv: Invitation) -> dict:
    """May the sign-up allowlist entry this claim created be removed now? {ok, reason, message}. Only when ALL hold: this claim created the entry (never one an administrator
    added by hand or that was already there); no OTHER invitation to the address is still usable (any business, any role); no account already exists for the address (the entry may
    be what lets that person create a business); and the address is not also permitted by the environment list or as an administrator address (removing the row would change nothing,
    and it is not ours to remove)."""
    def no(reason: str, message: str) -> dict:
        return {"ok": False, "reason": reason, "message": message}

    if inv.accepted_at:
        return no("accepted", "This invitation was accepted, so the address is in use.")
    if inv.allowlist_entry_id is None:
        return no("not_added_by_claim", "The address was already on the sign-up list before this invitation, so it is left alone.")
    row = db.get(RegistrationAllowlist, inv.allowlist_entry_id)
    if row is None:
        return no("already_removed", "The address is no longer on the sign-up list.")
    now = utcnow()
    other = db.scalar(select(Invitation.id).where(Invitation.email == inv.email, Invitation.id != inv.id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None), Invitation.expires_at > now).limit(1))
    if other is not None:
        return no("other_invitation", "Another invitation to this address is still valid, so it stays on the sign-up list.")
    if db.scalar(select(User.id).where(User.email == inv.email).limit(1)) is not None:
        return no("account_exists", "An account already exists for this address, and the sign-up list entry may be what lets them create a business, so it stays.")
    if inv.email in settings.registration_allowlist_set or inv.email in {registration.normalize_email(e) for e in settings.platform_admin_email_set}:
        return no("permitted_elsewhere", "This address is permitted by the server's own configuration, which is not changed here.")
    return {"ok": True, "reason": None, "message": "The address will be removed from the sign-up list."}


def revoke_claim_invitation(db: Session, tenant: Tenant, invitation_id: uuid.UUID, *, admin: User, ip: str | None = None, remove_from_allowlist: bool = False) -> dict:
    """Revoke an owner-claim invitation, and ONLY if asked also remove the sign-up allowlist entry it created, when nothing else needs it. History is kept either way: the invitation row,
    the audit entries and the fact of removal. Idempotent: repeating it on an already revoked invitation can still remove the entry."""
    inv = db.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.tenant_id == tenant.id, Invitation.role == Role.owner))
    if inv is None:
        raise ProvisionError(404, "not_found", "Invitation not found.")
    if inv.accepted_at:
        raise ProvisionError(409, "already_accepted", "This invitation was already accepted.")
    if not inv.revoked_at:
        inv.revoked_at = utcnow()
        audit(db, action="admin.claim_invitation_revoked", tenant_id=tenant.id, user_id=admin.id, entity_type="invitation", entity_id=inv.id, ip=ip, meta={"email": inv.email, "remove_from_allowlist_requested": remove_from_allowlist})
    out = {"state": "revoked", "allowlist": {"requested": remove_from_allowlist, "removed": False, "reason": None, "message": None}}
    if remove_from_allowlist:
        check = allowlist_removal_check(db, inv)
        out["allowlist"].update(reason=check["reason"], message=check["message"])
        if check["ok"]:
            entry_id = inv.allowlist_entry_id
            registration.remove(db, inv.email)
            out["allowlist"]["removed"] = True
            audit(db, action="admin.allowlist_removed_after_claim_revoke", tenant_id=tenant.id, user_id=admin.id, entity_type="registration_allowlist", entity_id=entry_id, ip=ip,
                  meta={"email": inv.email, "invitation_id": str(inv.id)})
        else:
            audit(db, action="admin.allowlist_kept_after_claim_revoke", tenant_id=tenant.id, user_id=admin.id, entity_type="registration_allowlist", entity_id=inv.id, ip=ip,
                  meta={"email": inv.email, "reason": check["reason"]})
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------- status and usage
def onboarding_status(db: Session, t: Tenant, owner_exists: bool) -> str:
    """has_account | live (a card is live) | ready (a location with a review link) | incomplete."""
    if owner_exists:
        return "has_account"
    if db.scalar(select(QRCard.id).where(QRCard.tenant_id == t.id, QRCard.status.in_(LIVE_CARD_STATUSES)).limit(1)) is not None:
        return "live"
    if db.scalar(select(Location.id).where(Location.tenant_id == t.id, Location.is_active.is_(True), Location.review_url.is_not(None), Location.review_url != "").limit(1)) is not None:
        return "ready"
    return "incomplete"


def ai_usage(db: Session, tenant_id: uuid.UUID) -> dict:
    """This month's AI use and cost for the business, from the same log and counters the plan limits are enforced against."""
    from app.services import entitlements as ent
    from app.services.ai_usage import usage_this_month

    e = ent.for_tenant(db, tenant_id)
    since = month_start()
    cost = db.scalar(select(func.coalesce(func.sum(AIGenerationLog.cost_usd), 0)).where(AIGenerationLog.tenant_id == tenant_id, AIGenerationLog.created_at >= since)) or 0
    calls = db.scalar(select(func.count()).select_from(AIGenerationLog).where(AIGenerationLog.tenant_id == tenant_id, AIGenerationLog.created_at >= since)) or 0
    return {"month_started": since, "review_writings": {"used": usage_this_month(db, tenant_id, field="review_generations"), "limit": e.review_generations},
            "replies": {"used": usage_this_month(db, tenant_id, field="review_replies"), "limit": e.review_replies}, "generations_logged": calls, "cost_usd": float(cost), "active": e.active}


# ---------------------------------------------------------------------------------------------------------------------------------------------------------- aggregate usage and cost
def managed_usage(db: Session) -> dict:
    """This month's AI use and estimated cost across the businesses FlowQR staff set up (origin 'admin').

    Consumption is counted from the same successful-generation log the plan limits are enforced against. Cost comes from the per-call ledger (the table the platform's AI budgets read, which
    outlives deleted businesses): each call carries the cost the provider reported or the cost estimated from the configured prices at the time. A call with no cost is NEVER priced by guessing:
    when AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK are set, its recorded tokens are priced at those figures and shown separately as `repriced_usd`; when they are not set, or the call recorded
    no tokens, it is counted in `unpriced_calls` and contributes nothing. `price_configured` says which case applies."""
    from app.models import AICallLedger
    from app.services import entitlements as ent
    from app.services import plans
    from app.services.ai_usage import price_known

    since = month_start()
    rows = db.execute(select(Tenant.id, Tenant.name, select(func.min(Location.city)).where(Location.tenant_id == Tenant.id).scalar_subquery(), Tenant.is_active, Subscription.status).outerjoin(Subscription, Subscription.tenant_id == Tenant.id).where(Tenant.origin == "admin")).all()
    ids = [r[0] for r in rows]
    used: dict = {}
    if ids:
        for tid, kind, n in db.execute(select(AIGenerationLog.tenant_id, AIGenerationLog.kind, func.count()).where(AIGenerationLog.tenant_id.in_(ids), AIGenerationLog.created_at >= since, AIGenerationLog.status == "ok")
                                       .group_by(AIGenerationLog.tenant_id, AIGenerationLog.kind)).all():
            u = used.setdefault(tid, {"review_generations": 0, "review_replies": 0})
            if kind in plans.REVIEW_GENERATION_KINDS:
                u["review_generations"] += n
            elif kind in plans.REPLY_KINDS:
                u["review_replies"] += n
    cost: dict = {}
    if ids:
        for tid, calls, recorded, unpriced, tin, tout in db.execute(
                select(AICallLedger.tenant_id, func.count(), func.coalesce(func.sum(AICallLedger.cost_usd), 0), func.count().filter(AICallLedger.cost_usd.is_(None)),
                       func.coalesce(func.sum(AICallLedger.input_tokens).filter(AICallLedger.cost_usd.is_(None)), 0), func.coalesce(func.sum(AICallLedger.output_tokens).filter(AICallLedger.cost_usd.is_(None)), 0))
                .where(AICallLedger.tenant_id.in_(ids), AICallLedger.created_at >= since, AICallLedger.status == "ok").group_by(AICallLedger.tenant_id)).all():
            cost[tid] = {"calls": calls, "recorded": float(recorded), "unpriced": int(unpriced), "tin": int(tin), "tout": int(tout)}
    pin, pout, priced = settings.ai_price_in_per_mtok, settings.ai_price_out_per_mtok, price_known()
    businesses, totals = [], {"businesses": len(rows), "active": 0, "suspended": 0, "access_revoked": 0, "review_writings_used": 0, "review_writings_allowed": 0, "replies_used": 0, "replies_allowed": 0,
                              "ai_calls": 0, "recorded_usd": 0.0, "repriced_usd": 0.0, "unpriced_calls": 0, "near_limit": 0}
    for tid, name, city, active, sub_status in rows:
        e = ent.for_tenant(db, tid)
        u = used.get(tid, {"review_generations": 0, "review_replies": 0})
        c = cost.get(tid, {"calls": 0, "recorded": 0.0, "unpriced": 0, "tin": 0, "tout": 0})
        # unpriced calls that recorded tokens can be priced at the configured prices; calls that recorded none stay unpriced
        repriced = (c["tin"] * pin + c["tout"] * pout) / 1_000_000 if priced else 0.0
        unpriced_left = c["unpriced"] if not priced or not (c["tin"] or c["tout"]) else 0
        revoked = sub_status == "expired"
        totals["active" if active else "suspended"] += 1
        totals["access_revoked"] += int(revoked)
        if e.active:  # an allowance only exists while access is on
            totals["review_writings_allowed"] += e.review_generations or 0
            totals["replies_allowed"] += e.review_replies or 0
        totals["review_writings_used"] += u["review_generations"]
        totals["replies_used"] += u["review_replies"]
        totals["ai_calls"] += c["calls"]
        totals["recorded_usd"] += c["recorded"]
        totals["repriced_usd"] += repriced
        totals["unpriced_calls"] += unpriced_left
        pct = max((u["review_generations"] / e.review_generations) if e.review_generations else 0, (u["review_replies"] / e.review_replies) if e.review_replies else 0)
        totals["near_limit"] += int(pct >= 0.8)
        businesses.append({"id": tid, "name": name, "city": city, "active": active, "access_revoked": revoked, "review_writings": {"used": u["review_generations"], "limit": e.review_generations},
                           "replies": {"used": u["review_replies"], "limit": e.review_replies}, "ai_calls": c["calls"], "recorded_usd": round(c["recorded"], 6), "repriced_usd": round(repriced, 6),
                           "unpriced_calls": unpriced_left, "percent_of_allowance": round(pct * 100)})
    businesses.sort(key=lambda b: (-(b["review_writings"]["used"] + b["replies"]["used"]), b["name"].lower()))
    totals["recorded_usd"], totals["repriced_usd"] = round(totals["recorded_usd"], 6), round(totals["repriced_usd"], 6)
    totals["estimated_usd"] = round(totals["recorded_usd"] + totals["repriced_usd"], 6)
    return {"month_started": since, "totals": totals, "businesses": businesses,
            "pricing": {"price_configured": priced, "input_per_million_tokens_usd": pin or None, "output_per_million_tokens_usd": pout or None,
                        "set_with": "AI_PRICE_IN_PER_MTOK and AI_PRICE_OUT_PER_MTOK",
                        "note": "Cost is the recorded cost per call where there is one. Calls without a recorded cost are priced from their recorded tokens only when the prices above are configured; otherwise they are counted as unpriced and add nothing."}}
