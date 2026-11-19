"""Contacts and consent. The rules this module enforces (they are the compliance model, so they are also the tests):

* A contact is NOT consent. Consent is a separate record per purpose (marketing | utility) holding the exact wording, its version, the source and the time.
* Customer-originated sources (qr_page, website_form, customer_message) are the customer's own act. Owner-side sources (owner_entry, csv_import, admin_entry) are the owner vouching for the
  customer, so they need an explicit attestation AND a written note of how consent was obtained. Nothing is ever assumed: review submissions, enquiries and imports create no consent by themselves.
* An opt-out (the customer's STOP, or the owner withdrawing) revokes the marketing consent, flags the contact and adds the number to the business's suppression list. After that ONLY a new consent
  from the customer themselves can lift it; an owner, a CSV file or an administrator cannot.
* Opting out of marketing does not silently revoke anything else: utility consent is a separate record and is only revoked by an explicit utility withdrawal.
"""
import csv
import io
import re
import uuid
from datetime import datetime, date

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Location, Tenant
from app.models.base import utcnow
from app.models.whatsapp import CONSENT_SOURCES, CUSTOMER_SOURCES, PURPOSES, WhatsAppConsent, WhatsAppContact, WhatsAppSuppression
from app.schemas.common import normalize_phone
from app.services.audit import audit
from app.services.whatsapp import WaError
from app.services.whatsapp import rules

OWNER_SOURCES = ("owner_entry", "csv_import", "admin_entry")
MAX_IMPORT_ROWS = 2000
MAX_IMPORT_BYTES = 300_000
MAX_TAGS = 10


def e164(raw: str | None) -> str:
    """'98765 43210', '+91 98765 43210' -> '+919876543210'. Raises WaError for anything that is not a usable mobile number."""
    try:
        norm = normalize_phone(raw)
    except ValueError:
        norm = None
    digits = re.sub(r"\D", "", norm or "")
    if not norm or not (10 <= len(digits) <= 15):
        raise WaError(422, "invalid_phone", "Enter a valid mobile number, for example 98765 43210.")
    return "+" + digits


def _tags(tags) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t)).strip()[:30]
        if t and t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out[:MAX_TAGS]


def _name(name: str | None) -> str | None:
    n = re.sub(r"[\x00-\x1f​-‏‪-‮⁦-⁩]", "", (name or "")).strip()[:120]
    return n or None


# ---- contacts
def get_contact(db: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> WhatsAppContact:
    c = db.scalar(select(WhatsAppContact).where(WhatsAppContact.id == contact_id, WhatsAppContact.tenant_id == tenant_id))
    if c is None:
        raise WaError(404, "not_found", "That customer was not found.")
    return c


def find_by_phone(db: Session, tenant_id: uuid.UUID, phone: str) -> WhatsAppContact | None:
    return db.scalar(select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.phone == phone))


def check_location(db: Session, tenant_id: uuid.UUID, location_id: uuid.UUID | None) -> uuid.UUID | None:
    """A customer can only be placed at one of THIS business's own locations."""
    if location_id is None:
        return None
    if db.scalar(select(Location.id).where(Location.id == location_id, Location.tenant_id == tenant_id)) is None:
        raise WaError(422, "invalid_location", "Choose one of your own locations.")
    return location_id


def create_contact(db: Session, tenant: Tenant, *, phone: str, name: str | None, tags, source: str, user_id: uuid.UUID | None, location_id: uuid.UUID | None = None) -> tuple[WhatsAppContact, bool]:
    """Get-or-create by number. Returns (contact, created)."""
    if source not in CONSENT_SOURCES:
        raise WaError(422, "invalid_source", "Unknown source.")
    p = e164(phone)
    existing = find_by_phone(db, tenant.id, p)
    if existing:
        if name and not existing.customer_name:
            existing.customer_name = _name(name)
        if tags:
            existing.tags = _tags([*existing.tags, *tags])
        if location_id and not existing.location_id:
            existing.location_id = check_location(db, tenant.id, location_id)
        return existing, False
    c = WhatsAppContact(tenant_id=tenant.id, phone=p, customer_name=_name(name), tags=_tags(tags), source=source, created_by=user_id, location_id=check_location(db, tenant.id, location_id))
    db.add(c)
    db.flush()
    return c, True


def update_contact(db: Session, contact: WhatsAppContact, *, name: str | None = None, tags=None, set_name: bool = False, set_tags: bool = False, location_id: uuid.UUID | None = None,
                   set_location: bool = False) -> WhatsAppContact:
    if set_location:
        contact.location_id = check_location(db, contact.tenant_id, location_id)
    if set_name:
        contact.customer_name = _name(name)
    if set_tags:
        contact.tags = _tags(tags)
    return contact


# ---- consent
def active_consent(db: Session, contact_id: uuid.UUID, purpose: str) -> WhatsAppConsent | None:
    return db.scalar(select(WhatsAppConsent).where(WhatsAppConsent.contact_id == contact_id, WhatsAppConsent.purpose == purpose, WhatsAppConsent.revoked_at.is_(None)))


def is_suppressed(db: Session, tenant_id: uuid.UUID, phone: str) -> bool:
    return db.scalar(select(WhatsAppSuppression.id).where(WhatsAppSuppression.tenant_id == tenant_id, WhatsAppSuppression.phone_hash == rules.phone_hash(tenant_id, phone))) is not None


def grant(db: Session, tenant: Tenant, contact: WhatsAppContact, purpose: str, source: str, *, user_id: uuid.UUID | None = None, attested: bool = False, evidence: str | None = None,
          ip: str | None = None, now: datetime | None = None, wording_text: str | None = None, wording_version: str | None = None) -> tuple[WhatsAppConsent, bool]:
    """Record a consent. Returns (consent, created); asking again for a purpose that is already consented returns the existing record (no duplicate, wording untouched)."""
    if purpose not in PURPOSES:
        raise WaError(422, "invalid_purpose", "Choose marketing or updates about a visit.")
    if source not in CONSENT_SOURCES:
        raise WaError(422, "invalid_source", "Unknown source.")
    if contact.tenant_id != tenant.id:
        raise WaError(404, "not_found", "That customer was not found.")  # defence in depth: the row-level policy already hides other businesses' rows
    note = re.sub(r"\s+", " ", (evidence or "")).strip()
    if source in OWNER_SOURCES:
        if not attested:
            raise WaError(422, "attestation_required", "Please confirm that this customer agreed to receive WhatsApp messages from you.")
        if len(note) < 10:
            raise WaError(422, "evidence_required", "Write a short note on how they agreed, for example: asked at the counter on 12 Nov and wrote it in the register.")
    suppressed = is_suppressed(db, tenant.id, contact.phone) if purpose in ("marketing", "occasion") else False  # STOP stops offers and greetings alike
    if suppressed and source not in CUSTOMER_SOURCES:
        raise WaError(409, "opted_out", "This customer asked to stop receiving offers. They can only be added again by the customer themselves, for example by agreeing on your review page or website form.")
    existing = active_consent(db, contact.id, purpose)
    if existing:
        return existing, False
    now = now or utcnow()
    row = WhatsAppConsent(tenant_id=tenant.id, contact_id=contact.id, purpose=purpose, source=source, wording_version=(wording_version or rules.WORDING_VERSION)[:24],
                          wording_text=(wording_text or rules.wording_for(purpose, tenant.name))[:600], evidence=note[:400] or None, granted_at=now, granted_by=user_id)
    db.add(row)
    if suppressed:  # the customer themselves agreed again: the opt-out is lifted
        db.execute(delete(WhatsAppSuppression).where(WhatsAppSuppression.tenant_id == tenant.id, WhatsAppSuppression.phone_hash == rules.phone_hash(tenant.id, contact.phone)))
        contact.marketing_opted_out_at = None
    if purpose == "marketing" and contact.marketing_opted_out_at and source in CUSTOMER_SOURCES:
        contact.marketing_opted_out_at = None
    db.flush()
    audit(db, action="whatsapp.consent_grant", tenant_id=tenant.id, user_id=user_id, entity_type="whatsapp_contact", entity_id=contact.id, meta={"purpose": purpose, "source": source, "wording": (wording_version or rules.WORDING_VERSION)}, ip=ip)
    return row, True


def withdraw(db: Session, tenant: Tenant, contact: WhatsAppContact, purpose: str, *, source: str, user_id: uuid.UUID | None = None, ip: str | None = None, now: datetime | None = None) -> bool:
    """Revoke the consent for a purpose. For marketing this also flags the contact and suppresses the number. Idempotent: returns False when there was nothing to revoke."""
    if purpose not in PURPOSES:
        raise WaError(422, "invalid_purpose", "Choose marketing or updates about a visit.")
    now = now or utcnow()
    row = active_consent(db, contact.id, purpose)
    changed = False
    if row:
        row.revoked_at, row.revoked_source, row.revoked_by = now, source, user_id
        changed = True
    if purpose == "marketing":
        if contact.marketing_opted_out_at is None:
            contact.marketing_opted_out_at = now
            changed = True
        _suppress(db, tenant.id, contact.phone, "customer_stop" if source == "customer_stop" else ("owner" if source == "owner" else "admin"), now)
        greet = active_consent(db, contact.id, "occasion")  # STOP also stops birthday and festival greetings (visit and enquiry updates are not affected)
        if greet:
            greet.revoked_at, greet.revoked_source, greet.revoked_by = now, source, user_id
            changed = True
    if changed:
        audit(db, action="whatsapp.consent_withdraw", tenant_id=tenant.id, user_id=user_id, entity_type="whatsapp_contact", entity_id=contact.id, meta={"purpose": purpose, "source": source}, ip=ip)
    return changed


def _suppress(db: Session, tenant_id: uuid.UUID, phone: str, reason: str, now: datetime) -> None:
    h = rules.phone_hash(tenant_id, phone)
    if db.scalar(select(WhatsAppSuppression.id).where(WhatsAppSuppression.tenant_id == tenant_id, WhatsAppSuppression.phone_hash == h)) is None:
        db.add(WhatsAppSuppression(tenant_id=tenant_id, phone_hash=h, reason=reason, created_at=now))
        db.flush()


def opt_out_by_phone(db: Session, tenant: Tenant, phone: str, *, now: datetime | None = None) -> bool:
    """The customer sent STOP. Works for a number that is not a contact too: it is suppressed so a later import or entry cannot re-add it."""
    now = now or utcnow()
    c = find_by_phone(db, tenant.id, phone)
    if c is None:
        _suppress(db, tenant.id, phone, "customer_stop", now)
        audit(db, action="whatsapp.consent_withdraw", tenant_id=tenant.id, entity_type="whatsapp_contact", meta={"purpose": "marketing", "source": "customer_stop", "known_contact": False})
        return True
    return withdraw(db, tenant, c, "marketing", source="customer_stop", now=now)


def has_consent(db: Session, tenant_id: uuid.UUID, contact: WhatsAppContact, purpose: str) -> tuple[bool, str]:
    """(ok, reason). The single question every send must pass; reasons are stable codes."""
    if contact.tenant_id != tenant_id:
        return False, "wrong_business"
    if purpose == "marketing":
        if contact.marketing_opted_out_at is not None or is_suppressed(db, tenant_id, contact.phone):
            return False, "opted_out"
        if active_consent(db, contact.id, "marketing") is None:
            return False, "no_marketing_consent"
        return True, "ok"
    if purpose == "utility":
        if active_consent(db, contact.id, "utility") is None:
            return False, "no_utility_consent"
        return True, "ok"
    return False, "invalid_purpose"


def has_occasion_consent(db: Session, tenant_id: uuid.UUID, contact: WhatsAppContact, category: str, category_confirmed: bool) -> tuple[bool, str]:
    """The consent a birthday or festival greeting needs. Fail closed.
    * STOP (or any offers opt-out) always blocks a greeting, whatever its category.
    * Occasion consent is always required.
    * If the approved category of the greeting is marketing, or WhatsApp has not yet reported it, offers consent is required too."""
    if contact.tenant_id != tenant_id:
        return False, "wrong_business"
    if contact.marketing_opted_out_at is not None or is_suppressed(db, tenant_id, contact.phone):
        return False, "opted_out"
    if active_consent(db, contact.id, "occasion") is None:
        return False, "no_occasion_consent"
    if category == "marketing" or not category_confirmed:
        if active_consent(db, contact.id, "marketing") is None:
            return False, "no_marketing_consent"
    return True, "ok"


# ---- birthday: a day and a month, never a year
def birthday_problem(day, month) -> str | None:
    if isinstance(day, bool) or isinstance(month, bool) or not isinstance(day, int) or not isinstance(month, int):
        return "Enter the birthday as a day and a month."
    try:
        date(2000, month, day)  # 2000 was a leap year: 29 February is a real birthday
    except ValueError:
        return "That day and month do not exist."
    return None


def require_attested(attested: bool, evidence: str | None) -> str:
    if not attested:
        raise WaError(422, "attestation_required", "Please confirm that this customer agreed to receive WhatsApp messages from you.")
    note = re.sub(r"\s+", " ", (evidence or "")).strip()
    if len(note) < 10:
        raise WaError(422, "evidence_required", "Write a short note on how they agreed, for example: asked at the counter on 12 Nov and wrote it in the register.")
    return note


def set_birthday(db: Session, contact: WhatsAppContact, day, month, *, attested: bool, evidence: str | None, user_id: uuid.UUID | None, ip: str | None = None) -> None:
    """Record (or clear, with both None) a customer's birth day and month. Setting it needs the same 'they agreed' confirmation as any other customer detail the owner types in."""
    if day is None and month is None:
        if contact.birth_day is not None:
            contact.birth_day = contact.birth_month = None
            audit(db, action="whatsapp.birthday_clear", tenant_id=contact.tenant_id, user_id=user_id, entity_type="whatsapp_contact", entity_id=contact.id, ip=ip)
        return
    if day is None or month is None:
        raise WaError(422, "invalid_birthday", "Enter both the day and the month of the birthday.")
    problem = birthday_problem(day, month)
    if problem:
        raise WaError(422, "invalid_birthday", problem)
    require_attested(attested, evidence)
    contact.birth_day, contact.birth_month = day, month
    audit(db, action="whatsapp.birthday_set", tenant_id=contact.tenant_id, user_id=user_id, entity_type="whatsapp_contact", entity_id=contact.id, ip=ip)  # the date itself is not written to the audit log


def erase_contact(db: Session, tenant: Tenant, contact: WhatsAppContact, user_id: uuid.UUID | None, ip: str | None = None) -> None:
    """Delete the person (number, name, tags, consent records). An opted-out number stays on the suppression list as a keyed hash so it cannot be re-added and messaged."""
    if contact.marketing_opted_out_at is not None:
        _suppress(db, tenant.id, contact.phone, "customer_stop", utcnow())
    cid = contact.id
    db.delete(contact)
    db.flush()
    audit(db, action="whatsapp.contact_erase", tenant_id=tenant.id, user_id=user_id, entity_type="whatsapp_contact", entity_id=cid, ip=ip)


# ---- listing, serialising, export
def consent_map(db: Session, contact_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    out = {cid: {"marketing": None, "utility": None, "occasion": None} for cid in contact_ids}
    if not contact_ids:
        return out
    for r in db.scalars(select(WhatsAppConsent).where(WhatsAppConsent.contact_id.in_(contact_ids), WhatsAppConsent.revoked_at.is_(None))):
        out[r.contact_id][r.purpose] = {"since": r.granted_at, "source": r.source, "wording_version": r.wording_version}
    return out


def serialize(c: WhatsAppContact, consents: dict | None = None) -> dict:
    consents = consents or {"marketing": None, "utility": None, "occasion": None}
    return {"id": c.id, "phone": c.phone, "customer_name": c.customer_name, "tags": c.tags or [], "location_id": c.location_id, "source": c.source, "created_at": c.created_at,
            "marketing": consents.get("marketing"), "utility": consents.get("utility"), "occasion": consents.get("occasion"), "opted_out": c.marketing_opted_out_at is not None, "opted_out_at": c.marketing_opted_out_at,
            "birth_day": c.birth_day, "birth_month": c.birth_month}


def list_contacts(db: Session, tenant_id: uuid.UUID, *, search: str | None, consent: str | None, limit: int, offset: int, location_id: uuid.UUID | None = None) -> tuple[int, list[dict]]:
    q = select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id)
    if location_id:
        q = q.where(WhatsAppContact.location_id == location_id)
    if search and search.strip():
        term = search.strip()
        digits = re.sub(r"\D", "", term)
        conds = [WhatsAppContact.customer_name.ilike(f"%{term}%")]
        if len(digits) >= 3:
            conds.append(WhatsAppContact.phone.like(f"%{digits}%"))
        q = q.where(or_(*conds))
    if consent == "marketing":
        q = q.where(WhatsAppContact.marketing_opted_out_at.is_(None), WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.purpose == "marketing", WhatsAppConsent.revoked_at.is_(None))))
    elif consent == "utility":
        q = q.where(WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.purpose == "utility", WhatsAppConsent.revoked_at.is_(None))))
    elif consent == "opted_out":
        q = q.where(WhatsAppContact.marketing_opted_out_at.is_not(None))
    elif consent == "none":
        q = q.where(~WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.revoked_at.is_(None))))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(q.order_by(WhatsAppContact.created_at.desc()).limit(limit).offset(offset)))
    cm = consent_map(db, [r.id for r in rows])
    return total, [serialize(r, cm[r.id]) for r in rows]


def counts(db: Session, tenant_id: uuid.UUID) -> dict:
    total = db.scalar(select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id)) or 0
    base = select(func.count(func.distinct(WhatsAppConsent.contact_id))).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.revoked_at.is_(None))
    marketing = db.scalar(base.where(WhatsAppConsent.purpose == "marketing")) or 0
    utility = db.scalar(base.where(WhatsAppConsent.purpose == "utility")) or 0
    occasion = db.scalar(base.where(WhatsAppConsent.purpose == "occasion")) or 0
    opted_out = db.scalar(select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.marketing_opted_out_at.is_not(None))) or 0
    return {"contacts": total, "marketing": marketing, "utility": utility, "occasion": occasion, "opted_out": opted_out}


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # a spreadsheet must never run a customer-supplied cell as a formula


def export_csv(db: Session, tenant_id: uuid.UUID) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["phone", "name", "tags", "marketing_consent_since", "marketing_consent_source", "utility_consent_since", "utility_consent_source", "opted_out_of_marketing", "source", "added",
                "occasion_consent_since", "occasion_consent_source", "birth_day", "birth_month"])
    rows = list(db.scalars(select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id).order_by(WhatsAppContact.created_at)))
    cm = consent_map(db, [r.id for r in rows])
    for r in rows:
        m, u, o = cm[r.id]["marketing"], cm[r.id]["utility"], cm[r.id]["occasion"]
        w.writerow([r.phone, _cell(r.customer_name), _cell("; ".join(r.tags or [])), m["since"].isoformat() if m else "", m["source"] if m else "", u["since"].isoformat() if u else "", u["source"] if u else "",
                    r.marketing_opted_out_at.isoformat() if r.marketing_opted_out_at else "", r.source, r.created_at.isoformat(),
                    o["since"].isoformat() if o else "", o["source"] if o else "", r.birth_day or "", r.birth_month or ""])
    return out.getvalue()


def _csv_birthday(row, bdcol, bmcol, bcol):
    """(day, month), None when the row has no birthday, or "bad". Never a year: a value with a year is refused, not trimmed."""
    try:
        if bcol is not None and bcol < len(row) and row[bcol].strip():
            parts = re.split(r"[-/ ]+", row[bcol].strip())
            if len(parts) != 2:
                return "bad"
            d, m = int(parts[0]), int(parts[1])
        elif bdcol is not None and bmcol is not None and bdcol < len(row) and bmcol < len(row) and row[bdcol].strip() and row[bmcol].strip():
            d, m = int(row[bdcol]), int(row[bmcol])
        else:
            return None
    except ValueError:
        return "bad"
    return "bad" if birthday_problem(d, m) else (d, m)


# ---- CSV import (explicit confirmation of valid consent; one attestation for the whole file, never per-row trust)
def import_csv(db: Session, tenant: Tenant, user_id: uuid.UUID, text_csv: str, *, attested: bool, evidence: str | None, purposes: list[str], ip: str | None = None) -> dict:
    if not attested:
        raise WaError(422, "attestation_required", "Please confirm that every customer in this file agreed to receive WhatsApp messages from you.")
    if len(re.sub(r"\s+", " ", evidence or "").strip()) < 10:
        raise WaError(422, "evidence_required", "Write a short note on how these customers agreed, for example: signed the visitor register at the clinic.")
    purposes = [p for p in dict.fromkeys(purposes or []) if p in PURPOSES]
    if not purposes:
        raise WaError(422, "invalid_purpose", "Choose what they agreed to: offers, updates about a visit, or both.")
    if len(text_csv.encode("utf-8", "ignore")) > MAX_IMPORT_BYTES:
        raise WaError(413, "file_too_large", "That file is too large. Split it into smaller files.")
    rows = list(csv.reader(io.StringIO(text_csv.lstrip("﻿"))))
    if not rows:
        raise WaError(422, "empty_file", "The file is empty.")
    header = [h.strip().lower() for h in rows[0]]
    pcol = next((i for i, h in enumerate(header) if h in ("phone", "mobile", "number", "phone number", "mobile number", "whatsapp")), None)
    if pcol is None:
        raise WaError(422, "no_phone_column", "The first row must name the columns, and one must be called phone.")
    ncol = next((i for i, h in enumerate(header) if h in ("name", "customer name", "customer_name")), None)
    tcol = next((i for i, h in enumerate(header) if h in ("tags", "tag", "group")), None)
    bdcol = next((i for i, h in enumerate(header) if h in ("birth_day", "birth day")), None)
    bmcol = next((i for i, h in enumerate(header) if h in ("birth_month", "birth month")), None)
    bcol = next((i for i, h in enumerate(header) if h in ("birthday", "birth date", "birthdate")), None)  # day and month only, like 14-03 or 14/03
    data = rows[1:]
    if len(data) > MAX_IMPORT_ROWS:
        raise WaError(413, "too_many_rows", f"That file has more than {MAX_IMPORT_ROWS} customers. Split it into smaller files.")
    seen: set[str] = set()
    result = {"rows": len(data), "added": 0, "already_there": 0, "consents_recorded": 0, "birthdays_set": 0, "skipped": 0, "errors": []}
    for n, row in enumerate(data, start=2):
        try:
            if pcol >= len(row) or not row[pcol].strip():
                raise WaError(422, "invalid_phone", "no number")
            phone = e164(row[pcol])
            if phone in seen:
                result["skipped"] += 1
                result["errors"].append({"row": n, "reason": "The same number appears twice in the file."}) if len(result["errors"]) < 20 else None
                continue
            seen.add(phone)
            name = row[ncol] if ncol is not None and ncol < len(row) else None
            tags = [t for t in re.split(r"[;|]", row[tcol])] if tcol is not None and tcol < len(row) else []
            with db.begin_nested():
                contact, created = create_contact(db, tenant, phone=phone, name=name, tags=tags, source="csv_import", user_id=user_id)
                result["added" if created else "already_there"] += 1
                bd = _csv_birthday(row, bdcol, bmcol, bcol)
                if bd == "bad":
                    if len(result["errors"]) < 20:
                        result["errors"].append({"row": n, "reason": "The birthday was not saved: use a day and a month like 14-03, with no year."})
                elif bd is not None:
                    contact.birth_day, contact.birth_month = bd  # the whole file is covered by the one confirmation that these customers agreed
                    result["birthdays_set"] += 1
                for p in purposes:
                    try:
                        _, made = grant(db, tenant, contact, p, "csv_import", user_id=user_id, attested=True, evidence=evidence, ip=ip)
                        result["consents_recorded"] += int(made)
                    except WaError as exc:
                        if exc.code != "opted_out":
                            raise
                        result["skipped"] += 1
                        if len(result["errors"]) < 20:
                            result["errors"].append({"row": n, "reason": "This number asked to stop receiving offers, so it was not added for offers."})
        except WaError as exc:
            result["skipped"] += 1
            if len(result["errors"]) < 20:
                result["errors"].append({"row": n, "reason": "Not a valid mobile number." if exc.code == "invalid_phone" else exc.message})
        except IntegrityError:
            result["skipped"] += 1
    audit(db, action="whatsapp.contact_import", tenant_id=tenant.id, user_id=user_id, entity_type="whatsapp_contact", meta={"rows": result["rows"], "added": result["added"], "purposes": purposes}, ip=ip)
    return result
