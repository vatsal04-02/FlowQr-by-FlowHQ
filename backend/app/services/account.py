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

from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.core.security import get_cipher
from app.models import (
    AIGenerationLog, AuditLog, AuthSession, CardAssignment, EmailVerificationToken, PasswordResetToken, CardOrder, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Invitation, Location,
    Membership, Payment, QRCard, QRStyle, ReplyDraft, ReplyLog, RetiredCampaignId, Review, ReviewCampaign, ReviewDraft, ReviewEvent,
    ReviewSession, ScanEvent, Subscription, Tenant, User,
)
from app.models.base import utcnow
from app.services.audit import audit
from app.models.autonomy import AgentAction, AgentActionApproval, AgentInterventionEvent, AgentRankFollowup, ConsentGrant
from app.models.rank import RankKeyword
from app.models.rank_grid import RankGrid, RankGridPoint, RankGridScan

log = logging.getLogger("flowqr.account")

# Never exported, whatever table they are in.
SECRET_COLUMNS = {"data", "refresh_token_encrypted", "access_token_encrypted", "access_token_expires_at", "password_hash", "token_hash", "csrf_token",
                  "visitor_hash", "logo_png", "idempotency_key", "publish_token", "dedupe_key",
                  "access_token_enc", "state_hash"}  # WhatsApp: the encrypted business token and the hashed one-time signup state
MAX_ROWS = 200_000
TABLES = [Location, GoogleConnection, GoogleLocation, Review, ReplyDraft, ReplyLog, QRCard, CardAssignment, ReviewCampaign, RetiredCampaignId,
          ReviewSession, ReviewDraft, ReviewEvent, ScanEvent, Subscription, Payment, CardOrder, AuditLog, AIGenerationLog, Invitation,
          # the autonomy records: what FlowQR proposed or did on the business's Google profile, who authorised it, every step, and what was measured afterwards
          AgentAction, AgentActionApproval, AgentInterventionEvent, AgentRankFollowup, ConsentGrant, RankKeyword, RankGrid, RankGridScan, RankGridPoint]

# Tenant-owned tables the first export did not include (a privacy audit compared every table that has a tenant_id with the list above): the knowledge base, scheduled posts and photos,
# stored Google snapshots and daily metrics, competitor and ranking records, notification choices, usage and plan history. `test_every_tenant_table_is_exported_or_exempt` fails
# when a new tenant table is added without either being listed here or being named in EXPORTED_ELSEWHERE, so the export cannot silently fall behind again.
_ALSO_EXPORTED = ("agent_runs", "agent_settings", "agent_task_events", "agent_tasks", "ai_call_ledger", "ai_outputs", "api_usage_ledger", "business_knowledge",
                  "competitor_snapshots", "gbp_metric_daily", "gbp_snapshots", "health_snapshots", "membership_locations", "notification_prefs", "pinned_competitors",
                  "promotional_grants", "rank_checks", "review_request_templates", "scheduled_media", "scheduled_posts", "subscription_events",
                  # added by the release since the first version of this list (prepaid checkout, QR/NFC destinations); the drift test found them
                  "prepaid_orders", "prepaid_price_overrides", "card_destination_history",
                  # admin-managed businesses: the offline agreement an administrator recorded
                  "tenant_agreements",
                  # and the administrator-handled export / deletion requests for a business that has no owner login (a person's own requests about their business are their data too)
                  "data_requests", "data_request_events",
                  # the website builder: the business's own website content, hostnames, image metadata, enquiries and publish history (image FILES are added to the ZIP by build_export)
                  "sites", "site_domains", "site_assets", "site_enquiries", "site_revisions",
                  # WhatsApp automation: the connection (never its token), the people, their consents, opt-out hashes, templates, delivery records, the sanitised webhook log and the add-on
                  "whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_suppressions", "whatsapp_templates", "whatsapp_messages", "whatsapp_webhook_events", "tenant_addons",
                  "whatsapp_automations", "whatsapp_automation_runs", "whatsapp_campaigns", "whatsapp_campaign_recipients",
                  # opt-in without a phone number on the page: the business's code and settings, and its opt-in keywords
                  "whatsapp_optin_settings", "whatsapp_optin_keywords", "whatsapp_festival_optins", "whatsapp_links", "whatsapp_link_clicks",
                  "whatsapp_conversation_settings", "whatsapp_conversations", "whatsapp_conversation_messages")
EXPORTED_ELSEWHERE = {"qr_styles"}  # written by build_export itself, together with the logo file


def _models_for(names) -> list:
    by_table = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers}
    return [by_table[n] for n in names]


TABLES += _models_for(_ALSO_EXPORTED)


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
        from app.services.sites import service as sites_svc

        for name, blob in sites_svc.export_files(db, tenant.id):
            z.writestr(name, blob)
            manifest["files"][name] = 1
        style = db.scalar(select(QRStyle).where(QRStyle.tenant_id == tenant.id))
        if style:
            put("qr_styles", [_row(style)])
            if style.logo_png:
                z.writestr("qr_logo.png", style.logo_png)
        manifest["notes"] = ["Google access tokens, password hashes and session tokens are never exported.",
                             "Customer review-assistant text is deleted automatically after the retention period, so older sessions may be empty.",
                             "Scan events keep no visitor identifiers.",
                             "Photo files you uploaded for scheduling are not included (the files are on your Google profile once published); their details are in scheduled_media.json."]
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
    from app.services.sites import service as sites_svc

    from app.services.whatsapp import connection as wa_connection

    wa_connection.on_tenant_delete(db, tenant_id)  # stops Meta sending this business's events to FlowQR (best effort; never blocks the deletion)
    sites_svc.on_tenant_delete(db, tenant_id)  # takes the website offline and holds its name for 90 days; raises (so nothing is deleted) if the hosting provider cannot remove it
    from app.services.cards import unassign_card
    cards_returned = 0
    for card in db.scalars(select(QRCard).where(QRCard.tenant_id == tenant_id)):
        if card.status.value == "retired":  # stays retired (never returns to stock); the tenant link is cleared when the business row goes
            continue
        unassign_card(db, card, "business_deleted")  # back to FlowHQ inventory as a clean, unassigned card (not a stale "active" one)
        cards_returned += 1
    db.flush()
    member_ids = list(db.scalars(select(Membership.user_id).where(Membership.tenant_id == tenant_id)))
    from app.models import Role
    notify = [(e, n) for e, n in db.execute(select(User.email, User.full_name).join(Membership, Membership.user_id == User.id)
                                            .where(Membership.tenant_id == tenant_id, Membership.role == Role.owner)).all()]  # told after it is done; the rows are gone by then
    business_name, slug = tenant.name, tenant.slug
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
    return {"deleted": True, "google_grants_revoked": revoked, "users_removed": orphaned, "cards_returned": cards_returned, "notify": notify, "business": business_name}


def due_for_deletion(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(Tenant.id).where(Tenant.deletion_scheduled_for.is_not(None), Tenant.deletion_scheduled_for <= utcnow())))


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# A PERSON deleting their OWN account. Not the same as deleting a business (above): a business is never deleted because one person leaves.
#
#   request  (signed in, typed email + password or a very recent sign-in)  -> a single-use link is emailed; only its hash is stored, it expires
#   confirm  (the link; no sign-in needed, like a password reset)           -> every session is revoked; deletion is scheduled after the same cancellable grace period as a business
#   cancel   (signed in, any time before the end)                          -> everything as it was
#   delete   (the hourly job, `delete_user`)                               -> memberships, sessions, tokens, invitations to this address and notification choices are removed; Google connections the
#            person made are revoked; their still-queued posts and photos are cancelled; their IP is removed from audit entries; the user row is ANONYMISED (a tombstone with no name,
#            email, phone, password or Google id) so nothing that points at the person points at anyone. Idempotent: a second run finds the tombstone and does nothing.
# What is never done: delete a business, leave a business without an owner, delete a platform administrator, or reveal anything about another account.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class SelfDeletionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, businesses: list[str] | None = None):
        super().__init__(message)
        self.code, self.status, self.businesses = code, status, businesses or []


RECENT_LINK_MINUTES = 10  # a repeated request inside this window does not create (or email) a second link


def sole_owner_businesses(db: Session, user_id: uuid.UUID) -> list[str]:
    """Names of the businesses this person is the ONLY owner of. Their own businesses, so naming them reveals nothing about anyone else."""
    from sqlalchemy import func

    from app.models import Role
    mine = db.execute(select(Tenant.id, Tenant.name).join(Membership, Membership.tenant_id == Tenant.id)
                      .where(Membership.user_id == user_id, Membership.role == Role.owner)).all()
    out = []
    for tid, name in mine:
        owners = db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == tid, Membership.role == Role.owner)) or 0
        if owners <= 1:
            out.append(name)
    return sorted(out)


def self_deletion_state(db: Session, user: User, *, now: datetime | None = None) -> dict:
    """What the person sees: none | awaiting_confirmation | scheduled, plus what would block it."""
    from app.core.db import set_rls_context
    set_rls_context(db, bypass=True)
    now = now or utcnow()
    if user.deletion_scheduled_for:
        state = "scheduled"
    elif user.deletion_token_hash and user.deletion_token_expires_at and user.deletion_token_expires_at > now:
        state = "awaiting_confirmation"
    else:
        state = "none"
    return {"state": state, "requested_at": user.deletion_requested_at, "confirm_link_expires_at": user.deletion_token_expires_at if state == "awaiting_confirmation" else None,
            "scheduled_for": user.deletion_scheduled_for, "grace_days": settings.account_deletion_grace_days, "blocked_by": sole_owner_businesses(db, user.id),
            "is_platform_admin": user.is_platform_admin}


def request_self_deletion(db: Session, user: User, *, now: datetime | None = None) -> str | None:
    """Create a confirmation link. Returns the raw token to email, or None when nothing new should be sent (already scheduled, or a fresh link already exists)."""
    from app.core.db import set_rls_context
    from app.core.security import hash_token, new_token
    set_rls_context(db, bypass=True)
    now = now or utcnow()
    if user.is_platform_admin:
        raise SelfDeletionError("platform_admin", "Platform administrator accounts are removed by FlowQR operations, not from here.", 403)
    blocked = sole_owner_businesses(db, user.id)
    if blocked:
        raise SelfDeletionError("sole_owner", "You are the only owner of " + ", ".join(blocked) + ". A business must always have an owner: make someone else an owner (Settings, Team) or delete the business first.", 409, blocked)
    if user.deletion_scheduled_for:
        return None  # already confirmed: idempotent
    fresh = (user.deletion_token_hash and user.deletion_requested_at and user.deletion_token_expires_at and user.deletion_token_expires_at > now
             and now - user.deletion_requested_at < timedelta(minutes=RECENT_LINK_MINUTES))
    if fresh:
        return None  # a retry of the same request: do not create or send a second link
    token = new_token(32)
    user.deletion_token_hash = hash_token(token)
    user.deletion_requested_at = now
    user.deletion_token_expires_at = now + timedelta(hours=settings.user_deletion_confirm_hours)
    return token


def confirm_self_deletion(db: Session, token: str, *, now: datetime | None = None) -> User:
    """Use the emailed link (single use). Revokes every session, then schedules the deletion. Raises SelfDeletionError('invalid_link') for anything wrong, with one message for every case."""
    from app.core.db import set_rls_context
    from app.core.security import hash_token
    set_rls_context(db, bypass=True)
    now = now or utcnow()
    user = db.scalar(select(User).where(User.deletion_token_hash == hash_token(token), User.deleted_at.is_(None)).with_for_update())
    if user is None or not user.deletion_token_expires_at or user.deletion_token_expires_at <= now:
        raise SelfDeletionError("invalid_link", "This link is invalid or has expired. Request deletion again from Settings, Account.", 400)
    user.deletion_token_hash = None  # single use
    user.deletion_token_expires_at = None
    user.deletion_confirmed_at = now
    user.deletion_scheduled_for = now + timedelta(days=settings.account_deletion_grace_days)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
    return user


def cancel_self_deletion(user: User) -> None:
    user.deletion_requested_at = user.deletion_token_hash = user.deletion_token_expires_at = user.deletion_confirmed_at = user.deletion_scheduled_for = None


def due_users(db: Session, *, now: datetime | None = None) -> list[uuid.UUID]:
    return list(db.scalars(select(User.id).where(User.deletion_scheduled_for.is_not(None), User.deletion_scheduled_for <= (now or utcnow()), User.deleted_at.is_(None))))


def delete_user(db: Session, user_id: uuid.UUID, *, provider=None, now: datetime | None = None) -> dict:
    """Anonymise one person whose scheduled deletion is due. Needs a bypass-RLS session (the job's). Returns what happened; `email` is the address to tell (it no longer exists afterwards)."""
    from app.core.db import set_rls_context
    set_rls_context(db, bypass=True)
    now = now or utcnow()
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        return {"deleted": False, "reason": "missing"}
    if user.deleted_at is not None:
        return {"deleted": False, "reason": "already_deleted"}  # idempotent
    if not user.deletion_scheduled_for or user.deletion_scheduled_for > now:
        return {"deleted": False, "reason": "not_due"}
    email, name = user.email, user.full_name
    if user.is_platform_admin or sole_owner_businesses(db, user.id):  # re-checked now: things change during a grace period
        cancel_self_deletion(user)
        audit(db, action="account.user_deletion_blocked", user_id=user.id, entity_type="user", entity_id=user.id,
              meta={"reason": "platform_admin" if user.is_platform_admin else "sole_owner"})
        db.commit()
        return {"deleted": False, "reason": "blocked", "email": email, "name": name, "user_id": user.id}

    revoked = 0
    for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.connected_by == user.id)):  # the Google grant this person made is theirs: revoke it
        if conn.refresh_token_encrypted and conn.status != GoogleConnectionStatus.disconnected:
            try:
                from app.services import google as g
                (provider or g.get_google_provider()).revoke(get_cipher().decrypt(conn.refresh_token_encrypted))
                revoked += 1
            except Exception as exc:  # noqa: BLE001 - best effort; the tokens are wiped below either way
                log.warning("Google revoke failed during personal account deletion: %s", type(exc).__name__)
        conn.refresh_token_encrypted = conn.access_token_encrypted = conn.access_token_expires_at = None
        conn.status = GoogleConnectionStatus.disconnected
        conn.disconnected_at = now
        for gl in db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id)):
            gl.selected = False

    from app.models import NotificationPref, ScheduledMedia, ScheduledPost
    posts = db.execute(update(ScheduledPost).where(ScheduledPost.created_by == user.id, ScheduledPost.status.in_(("approved", "scheduled"))).values(status="canceled")).rowcount or 0
    media = db.execute(update(ScheduledMedia).where(ScheduledMedia.created_by == user.id, ScheduledMedia.status == "scheduled").values(status="canceled")).rowcount or 0
    memberships = db.execute(delete(Membership).where(Membership.user_id == user.id)).rowcount or 0
    invitations = db.execute(delete(Invitation).where(Invitation.email == email.lower())).rowcount or 0
    db.execute(delete(NotificationPref).where(NotificationPref.user_id == user.id))
    sessions = db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)).rowcount or 0
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
    ips = db.execute(update(AuditLog).where(AuditLog.user_id == user.id, AuditLog.ip.is_not(None)).values(ip=None)).rowcount or 0  # the IP only; the entry stays

    user.email = f"deleted-{user.id}@deleted.invalid"
    user.full_name, user.phone, user.password_hash, user.google_sub = "Deleted user", None, None, None
    user.is_active, user.email_verified_at, user.last_login_at = False, None, None
    user.age_confirmed_at = user.age_declaration_version = None
    user.deletion_token_hash = user.deletion_token_expires_at = None
    user.deleted_at = now
    audit(db, action="account.user_deleted", user_id=user.id, entity_type="user", entity_id=user.id,
          meta={"memberships_removed": memberships, "sessions_removed": sessions, "invitations_removed": invitations, "google_grants_revoked": revoked,
                "posts_cancelled": posts, "photos_cancelled": media, "audit_ips_removed": ips})
    db.commit()
    return {"deleted": True, "email": email, "name": name, "user_id": user.id}
