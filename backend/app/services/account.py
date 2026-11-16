"""Account lifecycle: owner data export and account deletion.

Export is everything FlowQR holds for ONE business, as JSON files in a ZIP. It never contains secrets: Google tokens,
password hashes, session tokens and hashed-visitor identifiers are excluded by column name.

Deletion is two-step: the owner schedules it (a grace period they can cancel), and a daily job performs it. The job revokes
Google access first (best effort), then deletes the tenant; every tenant-owned table cascades. Printed cards survive as
unassigned cards (they are FlowHQ inventory), so a deleted business's QR codes show "not set up" rather than another
business's page.
"""
import io
import json
import logging
import uuid
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from sqlalchemy import delete, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_cipher
from app.models import (
    AIGenerationLog, AuditLog, CardAssignment, CardOrder, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Invitation, Location,
    Membership, Payment, QRCard, QRStyle, ReplyDraft, ReplyLog, RetiredCampaignId, Review, ReviewCampaign, ReviewDraft, ReviewEvent,
    ReviewSession, ScanEvent, Subscription, Tenant, User,
)
from app.models.base import utcnow
from app.models.autonomy import AgentAction, AgentActionApproval, AgentInterventionEvent, AgentRankFollowup
from app.models.rank import RankKeyword
from app.models.rank_grid import RankGrid, RankGridPoint, RankGridScan

log = logging.getLogger("flowqr.account")

# Never exported, whatever table they are in.
SECRET_COLUMNS = {"refresh_token_encrypted", "access_token_encrypted", "access_token_expires_at", "password_hash", "token_hash", "csrf_token",
                  "visitor_hash", "logo_png", "idempotency_key"}
MAX_ROWS = 200_000
TABLES = [Location, GoogleConnection, GoogleLocation, Review, ReplyDraft, ReplyLog, QRCard, CardAssignment, ReviewCampaign, RetiredCampaignId,
          ReviewSession, ReviewDraft, ReviewEvent, ScanEvent, Subscription, Payment, CardOrder, AuditLog, AIGenerationLog, Invitation,
          # the autonomy records: what FlowQR proposed or did on the business's Google profile, who authorised it, every step, and what was measured afterwards
          AgentAction, AgentActionApproval, AgentInterventionEvent, AgentRankFollowup, RankKeyword, RankGrid, RankGridScan, RankGridPoint]


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, bytes):
        return None
    return v


def _row(obj) -> dict:
    return {c.key: _plain(getattr(obj, c.key)) for c in inspect(type(obj)).mapper.column_attrs if c.key not in SECRET_COLUMNS}


def build_export(db: Session, tenant: Tenant) -> tuple[bytes, dict]:
    """(zip bytes, manifest). Caller must have the tenant's RLS context (or bypass) so only this business's rows are visible."""
    buf, manifest = io.BytesIO(), {"business": tenant.name, "exported_at": utcnow().isoformat(), "files": {}, "truncated": []}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, rows: list[dict]):
            z.writestr(f"{name}.json", json.dumps(rows, indent=1, default=str, ensure_ascii=False))
            manifest["files"][f"{name}.json"] = len(rows)

        put("business", [{c.key: _plain(getattr(tenant, c.key)) for c in inspect(Tenant).mapper.column_attrs}])
        members = db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.tenant_id == tenant.id)).all()
        put("team", [{"email": u.email, "name": u.full_name, "role": m.role.value, "all_locations": m.all_locations, "joined": _plain(m.created_at)} for m, u in members])
        for model in TABLES:
            rows = db.scalars(select(model).where(model.tenant_id == tenant.id).limit(MAX_ROWS + 1)).all()
            if len(rows) > MAX_ROWS:
                rows = rows[:MAX_ROWS]
                manifest["truncated"].append(model.__tablename__)
            put(model.__tablename__, [_row(r) for r in rows])
        style = db.scalar(select(QRStyle).where(QRStyle.tenant_id == tenant.id))
        if style:
            put("qr_styles", [_row(style)])
            if style.logo_png:
                z.writestr("qr_logo.png", style.logo_png)
        manifest["notes"] = ["Google access tokens, password hashes and session tokens are never exported.",
                             "Customer review-assistant text is deleted automatically after the retention period, so older sessions may be empty.",
                             "Scan events keep no visitor identifiers."]
        z.writestr("README.json", json.dumps(manifest, indent=1))
    return buf.getvalue(), manifest


def schedule_deletion(db: Session, tenant: Tenant) -> datetime:
    now = utcnow()
    tenant.deletion_requested_at = now
    tenant.deletion_scheduled_for = now + timedelta(days=settings.account_deletion_grace_days)
    return tenant.deletion_scheduled_for


def cancel_deletion(tenant: Tenant) -> None:
    tenant.deletion_requested_at = tenant.deletion_scheduled_for = None


def delete_tenant(db: Session, tenant_id: uuid.UUID, *, provider=None) -> dict:
    """Irreversibly delete one business and everything it owns. Needs a bypass-RLS session (the daily job's)."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return {"deleted": False, "reason": "missing"}
    revoked = 0
    for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant_id)):
        if conn.refresh_token_encrypted and conn.status != GoogleConnectionStatus.disconnected:
            try:  # best effort: the data is deleted either way; this stops Google keeping the grant alive
                from app.services import google as g
                (provider or g.get_google_provider()).revoke(get_cipher().decrypt(conn.refresh_token_encrypted))
                revoked += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("Google revoke failed during account deletion: %s", type(exc).__name__)
    from app.services.cards import unassign_card
    cards_returned = 0
    for card in db.scalars(select(QRCard).where(QRCard.tenant_id == tenant_id)):
        if card.status.value == "retired":  # stays retired (never returns to stock); the tenant link is cleared when the business row goes
            continue
        unassign_card(db, card, "business_deleted")  # back to FlowHQ inventory as a clean, unassigned card (not a stale "active" one)
        cards_returned += 1
    db.flush()
    member_ids = list(db.scalars(select(Membership.user_id).where(Membership.tenant_id == tenant_id)))
    slug = tenant.slug
    db.execute(text("SELECT set_config('app.history_purge', 'on', true)"))  # the autonomy history is append-only; only deleting the whole business may erase it
    db.execute(delete(Tenant).where(Tenant.id == tenant_id))
    orphaned = 0
    for uid in member_ids:  # people whose only business this was lose their account too; platform admins never do
        user = db.get(User, uid)
        if user and not user.is_platform_admin and not db.scalar(select(Membership.id).where(Membership.user_id == uid).limit(1)):
            db.execute(delete(User).where(User.id == uid))
            orphaned += 1
    db.add(AuditLog(tenant_id=None, user_id=None, action="account.deleted", entity_type="tenant", entity_id=str(tenant_id),
                    meta={"slug": slug, "google_grants_revoked": revoked, "users_removed": orphaned, "cards_returned": cards_returned}, created_at=utcnow()))
    db.commit()
    return {"deleted": True, "google_grants_revoked": revoked, "users_removed": orphaned, "cards_returned": cards_returned}


def due_for_deletion(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(Tenant.id).where(Tenant.deletion_scheduled_for.is_not(None), Tenant.deletion_scheduled_for <= utcnow())))
