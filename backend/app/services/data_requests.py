"""Administrator-handled data export and deletion requests for a business that has no owner login.

A business with an owner uses Settings > Account (services/account.py). A business that FlowQR staff set up has no owner, so nobody can do that for it. This is the audited way for a
shopkeeper (or someone speaking for the shop) to ask for their data or its erasure, and for an administrator to act on it SAFELY. The rules, each of them a test:

  * a request can only be made for a business with no owner; the moment someone claims the business the request can no longer be acted on (the owner has the real tools)
  * nothing happens without VERIFICATION of who is asking, recorded by an administrator: by calling the shop back on the number ALREADY on the record, meeting in person, a WhatsApp message
    from that number, or an email from the address already on the record. A contact detail that was merely given in the request does not count
  * EXPORT: an administrator generates the same ZIP an owner would get (no secrets), hands it to the verified person, and marks it delivered. Nothing is emailed by the system
  * DELETION: never automatic and never by the daily job (this does not set the business's own deletion schedule). After verification there is a cooling-off period
    (ACCOUNT_DELETION_GRACE_DAYS, like an owner's); then an administrator executes it by typing the business name and acknowledging what is erased. A paid subscription must be cancelled first
  * every step is an append-only event and an audit entry; the request and its history outlive the deleted business, and the requester's contact detail is erased when the request ends
"""
from __future__ import annotations

import re
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DataRequest, DataRequestEvent, Location, QRCard, Subscription, Tenant
from app.models.base import utcnow
from app.services import provisioning as prov
from app.services.audit import audit

KINDS = ("export", "deletion")
ROLES = ("owner", "representative", "other")
RECEIVED_VIA = ("phone", "in_person", "whatsapp", "email", "paper", "other")
# how the administrator established that the person asking really speaks for the business
VERIFICATION_METHODS = ("callback_to_shop_phone", "in_person_at_shop", "whatsapp_from_shop_phone", "email_from_known_address", "other")
DELIVERY_METHODS = ("handed_over_in_person", "emailed_to_verified_address", "sent_on_whatsapp_to_verified_number", "other")
ACTIVE_PAID = {"active", "past_due", "pending", "authenticated"}
OPEN = ("open", "verified")


def _event(db: Session, req: DataRequest, admin, action: str, detail: str | None = None) -> None:
    db.add(DataRequestEvent(request_id=req.id, tenant_id=req.tenant_id, at=utcnow(), actor_id=admin.id if admin else None, action=action, detail=(detail or None) and detail[:300]))


def _audit(db: Session, req: DataRequest, admin, action: str, ip: str | None, **meta) -> None:
    audit(db, action=f"admin.data_request_{action}", tenant_id=req.tenant_id, user_id=admin.id, entity_type="data_request", entity_id=req.id, ip=ip, meta={"kind": req.kind, "business": req.business_name, **meta})


def get(db: Session, request_id: uuid.UUID) -> DataRequest:
    req = db.get(DataRequest, request_id)
    if req is None:
        raise prov.ProvisionError(404, "not_found", "Request not found.")
    return req


def _ownerless_tenant(db: Session, req: DataRequest) -> Tenant:
    t = db.get(Tenant, req.tenant_id) if req.tenant_id else None
    if t is None:
        raise prov.ProvisionError(409, "business_gone", "This business no longer exists.")
    if prov.has_owner(db, t.id):
        raise prov.ProvisionError(409, "has_owner", "This business now has an owner. They can export or delete their data from Settings, so this request can no longer be acted on here.")
    return t


def create(db: Session, tenant: Tenant, *, admin, kind: str, requester_name: str, requester_role: str, received_via: str, requester_contact: str | None, note: str | None, ip: str | None = None) -> DataRequest:
    if prov.has_owner(db, tenant.id):
        raise prov.ProvisionError(409, "has_owner", "This business has an owner. They can export or delete their data from Settings > Account.")
    if db.scalar(select(DataRequest.id).where(DataRequest.tenant_id == tenant.id, DataRequest.kind == kind, DataRequest.status.in_(OPEN))):
        raise prov.ProvisionError(409, "already_open", f"There is already an open {kind} request for this business.")
    req = DataRequest(tenant_id=tenant.id, business_name=tenant.name, kind=kind, status="open", requester_name=requester_name, requester_role=requester_role, received_via=received_via,
                      requester_contact=requester_contact, request_note=note, created_by=admin.id, created_at=utcnow())
    db.add(req)
    db.flush()
    _event(db, req, admin, "requested", f"{requester_role} {requester_name} asked by {received_via}")
    _audit(db, req, admin, "created", ip, requester_role=requester_role, received_via=received_via)
    return req


def _digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")[-10:]


def verify(db: Session, req: DataRequest, *, admin, method: str, contacted_on: str | None, note: str | None, ip: str | None = None) -> DataRequest:
    """Record that an administrator established who is asking. A callback or WhatsApp must be to the number on the record; an email to the address on the record."""
    if req.status != "open":
        raise prov.ProvisionError(409, "not_open", "Only an open request can be verified.")
    t = _ownerless_tenant(db, req)
    matched: bool | None = None
    if method in ("callback_to_shop_phone", "whatsapp_from_shop_phone"):
        if not t.phone:
            raise prov.ProvisionError(422, "no_phone_on_record", "This business has no phone number on record to verify against. Add it first, or use another method.")
        matched = bool(_digits(contacted_on)) and _digits(contacted_on) == _digits(t.phone)
        if not matched:
            raise prov.ProvisionError(422, "not_the_number_on_record", "That is not the phone number on the business record. Verify using the number already on file, not one given in the request.")
    elif method == "email_from_known_address":
        if not t.email:
            raise prov.ProvisionError(422, "no_email_on_record", "This business has no email address on record to verify against. Add it first, or use another method.")
        matched = (contacted_on or "").strip().lower() == t.email.strip().lower()
        if not matched:
            raise prov.ProvisionError(422, "not_the_email_on_record", "That is not the email address on the business record. Verify using the address already on file.")
    now = utcnow()
    req.status, req.verification_method, req.verification_note, req.contact_matched_record = "verified", method, note, matched
    req.verified_by, req.verified_at = admin.id, now
    if req.kind == "deletion":
        req.eligible_at = now + timedelta(days=settings.account_deletion_grace_days)
    _event(db, req, admin, "verified", f"{method}" + (" (contact matches the record)" if matched else "") + (f": {note}" if note else ""))
    _audit(db, req, admin, "verified", ip, method=method, contact_matched_record=matched, eligible_at=req.eligible_at.isoformat() if req.eligible_at else None)
    return req


def _close(db: Session, req: DataRequest, admin, status: str, reason: str, ip: str | None) -> DataRequest:
    if req.status not in OPEN:
        raise prov.ProvisionError(409, "already_resolved", "This request is already resolved.")
    req.status, req.resolved_by, req.resolved_at, req.resolution, req.requester_contact = status, admin.id, utcnow(), reason[:300], None
    _event(db, req, admin, status, reason)
    _audit(db, req, admin, status, ip, reason=reason)
    return req


def reject(db: Session, req: DataRequest, *, admin, reason: str, ip: str | None = None) -> DataRequest:
    return _close(db, req, admin, "rejected", reason, ip)


def cancel(db: Session, req: DataRequest, *, admin, reason: str, ip: str | None = None) -> DataRequest:
    return _close(db, req, admin, "cancelled", reason, ip)


def generate_export(db: Session, req: DataRequest, *, admin, ip: str | None = None) -> tuple[bytes, dict, str]:
    """The business's data as a ZIP, for an administrator to hand over. Only for a verified export request. Nothing is sent by the system."""
    from app.services import account as account_svc

    if req.kind != "export" or req.status != "verified":
        raise prov.ProvisionError(409, "not_ready", "The identity of the person asking must be verified before the export can be generated.")
    t = _ownerless_tenant(db, req)
    data, manifest = account_svc.build_export(db, t)
    req.export_count += 1
    _event(db, req, admin, "export_generated", f"{len(manifest['files'])} files, {len(data)} bytes")
    _audit(db, req, admin, "export_generated", ip, files=len(manifest["files"]), bytes=len(data))
    return data, manifest, t.slug


def complete_export(db: Session, req: DataRequest, *, admin, delivery: str, note: str | None, ip: str | None = None) -> DataRequest:
    if req.kind != "export" or req.status != "verified":
        raise prov.ProvisionError(409, "not_ready", "Only a verified export request can be completed.")
    if req.export_count < 1:
        raise prov.ProvisionError(409, "not_generated", "Generate the export first, then record how it was handed over.")
    return _close_fulfilled(db, req, admin, f"export delivered: {delivery}" + (f" ({note})" if note else ""), ip)


def _close_fulfilled(db: Session, req: DataRequest, admin, resolution: str, ip: str | None) -> DataRequest:
    req.status, req.resolved_by, req.resolved_at, req.resolution, req.requester_contact = "fulfilled", admin.id, utcnow(), resolution[:300], None
    _event(db, req, admin, "fulfilled", resolution)
    _audit(db, req, admin, "fulfilled", ip, resolution=resolution)
    return req


def deletion_state(db: Session, req: DataRequest) -> dict:
    """What an administrator needs before executing: whether the cooling-off has passed, whether a paid subscription blocks it, and what will be erased or returned."""
    t = db.get(Tenant, req.tenant_id) if req.tenant_id else None
    if t is None:
        return {"ready": False, "reason": "business_gone"}
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == t.id))
    paid = bool(sub and sub.razorpay_subscription_id and sub.status in ACTIVE_PAID)
    now = utcnow()
    waiting = req.eligible_at is not None and req.eligible_at > now
    reason = ("has_owner" if prov.has_owner(db, t.id) else "not_verified" if req.status != "verified" else "cooling_off" if waiting else "paid_subscription" if paid else None)
    return {"ready": reason is None and req.kind == "deletion", "reason": reason, "eligible_at": req.eligible_at,
            "impact": {"locations": db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == t.id)) or 0,
                       "cards": db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id)) or 0,
                       "live_cards": db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id, QRCard.status.in_(prov.LIVE_CARD_STATUSES))) or 0}}


def execute_deletion(db: Session, req: DataRequest, *, admin, confirm_name: str, acknowledge: bool, ip: str | None = None) -> dict:
    """Irreversibly delete the business. Explicit administrator action only: verified, past the cooling-off, name typed exactly, consequences acknowledged."""
    from app.services import account as account_svc

    if req.kind != "deletion":
        raise prov.ProvisionError(409, "not_deletion", "This is not a deletion request.")
    t = _ownerless_tenant(db, req)
    st = deletion_state(db, req)
    if st["reason"] == "not_verified":
        raise prov.ProvisionError(409, "not_verified", "Verify who is asking before deleting anything.")
    if st["reason"] == "cooling_off":
        raise prov.ProvisionError(409, "cooling_off", f"Deletion is not allowed before {req.eligible_at.date().isoformat()}. The waiting period gives the shop time to change its mind.")
    if st["reason"] == "paid_subscription":
        raise prov.ProvisionError(409, "cancel_subscription_first", "Cancel the paid subscription first, so the business is not charged again.")
    if confirm_name.strip() != t.name:
        raise prov.ProvisionError(422, "name_mismatch", "Type the business name exactly as shown to confirm.")
    if not acknowledge:
        raise prov.ProvisionError(422, "not_acknowledged", "Confirm that you understand this permanently erases the business and returns its cards to stock.")
    impact = st["impact"]
    tenant_id, name = t.id, t.name
    # Written in the SAME transaction as the deletion (delete_tenant commits it): the request ends, the contact detail is erased, and an audit entry that survives the business is added.
    req.status, req.resolved_by, req.resolved_at, req.requester_contact = "fulfilled", admin.id, utcnow(), None
    req.resolution = f"deleted: {impact['locations']} locations, {impact['cards']} cards returned to stock"[:300]
    _event(db, req, admin, "deleted", req.resolution)
    audit(db, action="admin.data_request_deletion_executed", tenant_id=None, user_id=admin.id, entity_type="data_request", entity_id=req.id, ip=ip,
          meta={"business": name, "tenant_id": str(tenant_id), "verified_by": str(req.verified_by) if req.verified_by else None, "verification_method": req.verification_method, **impact})
    db.flush()
    out = account_svc.delete_tenant(db, tenant_id)
    return {"deleted": bool(out.get("deleted")), "cards_returned": out.get("cards_returned", 0), "google_grants_revoked": out.get("google_grants_revoked", 0)}


def serialize(db: Session, req: DataRequest) -> dict:
    from app.models import User

    def who(uid):
        return db.scalar(select(User.email).where(User.id == uid)) if uid else None

    events = db.scalars(select(DataRequestEvent).where(DataRequestEvent.request_id == req.id).order_by(DataRequestEvent.at)).all()
    out = {"id": req.id, "kind": req.kind, "status": req.status, "business_name": req.business_name, "requester_name": req.requester_name, "requester_role": req.requester_role,
           "received_via": req.received_via, "requester_contact": req.requester_contact, "request_note": req.request_note, "created_at": req.created_at, "created_by": who(req.created_by),
           "verification_method": req.verification_method, "verification_note": req.verification_note, "contact_matched_record": req.contact_matched_record, "verified_at": req.verified_at,
           "verified_by": who(req.verified_by), "eligible_at": req.eligible_at, "resolved_at": req.resolved_at, "resolved_by": who(req.resolved_by), "resolution": req.resolution,
           "export_count": req.export_count,
           "events": [{"at": e.at, "action": e.action, "by": who(e.actor_id), "detail": e.detail} for e in events]}
    if req.kind == "deletion" and req.status in OPEN:
        out["deletion"] = deletion_state(db, req)
    return out
