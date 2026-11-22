"""Balanced Autonomy: proposed Google Business Profile actions, the approvals that authorise them, the append-only history of everything that happened,
and the ranking follow-ups that measure what happened afterwards. All tenant-scoped (RLS), except PlatformControl (one platform-wide switchboard).

AgentAction is the ONE record of "FlowQR wants to change something on a Google profile": what is there now, what it would become, where the new value
came from, which policy level it falls under, who authorised it, what Google answered and whether reading the profile back confirmed it."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow

ACTION_STATUSES = ("pending_approval", "approved", "executing", "executed", "failed", "rejected", "expired", "invalidated", "blocked", "canceled", "recommended", "superseded")
LIVE_STATUSES = ("recommended", "pending_approval", "approved", "executing", "executed")  # an action in one of these owns its idempotency key


class AgentAction(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        CheckConstraint("status in (" + ",".join(f"'{s}'" for s in ACTION_STATUSES) + ")", name="ck_agent_action_status"),
        CheckConstraint("policy_level between 1 and 3", name="ck_agent_action_level"),
        Index("uq_agent_actions_idempotency", "tenant_id", "idempotency_key", unique=True, postgresql_where=text("status in ('recommended','pending_approval','approved','executing','executed')")),
        Index("uq_agent_actions_inflight", "google_location_id", "field_key", unique=True, postgresql_where=text("status = 'executing'")),  # one write in flight per location+field
        Index("ix_agent_actions_due", "status", "next_attempt_at"),
        Index("ix_agent_actions_tenant", "tenant_id", "status", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column()  # the agent_tasks row this came from, when there is one
    subject_type: Mapped[str | None] = mapped_column(String(16))  # post | photo | reply when this action governs publishing one of those; NULL = a profile field
    subject_id: Mapped[uuid.UUID | None] = mapped_column()
    action_type: Mapped[str] = mapped_column(String(40))
    field_key: Mapped[str] = mapped_column(String(40))  # description | hours | website | phone | additional_categories | primary_category | ...
    trigger: Mapped[str] = mapped_column(String(60))  # what noticed the problem, e.g. "optimizer:description", "rank:weak_visibility", "owner_request"
    problem: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    expected_outcome: Mapped[str] = mapped_column(Text)  # never a ranking promise
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[dict] = mapped_column(JSONB, default=dict)  # the verified source of the new value: {"kind", "refs"...}
    current_value: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"value": ...} as Google held it when proposed
    proposed_value: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"value": ...}
    base_fingerprint: Mapped[str] = mapped_column(String(64))  # of the Google value this was proposed against
    value_hash: Mapped[str] = mapped_column(String(64))  # of the proposed value
    facts_fingerprint: Mapped[str] = mapped_column(String(64))  # of the verified facts it was built from
    idempotency_key: Mapped[str] = mapped_column(String(64))
    policy_level: Mapped[int] = mapped_column(SmallInteger)  # 1 autonomous | 2 conditionally autonomous | 3 owner authorisation. Computed by code, never by the model.
    effective_type: Mapped[str] = mapped_column(String(40))  # the type the policy treated it as (an escalation can change it)
    risk_level: Mapped[str] = mapped_column(String(8))
    policy_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    authorization: Mapped[str] = mapped_column(String(16))  # policy | preauthorized | owner: who may authorise it
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    proposed_by: Mapped[str] = mapped_column(String(8))  # agent | user
    proposed_by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    google_result: Mapped[dict | None] = mapped_column(JSONB)
    verification: Mapped[dict | None] = mapped_column(JSONB)
    validation_status: Mapped[str | None] = mapped_column(String(12))  # validated | rejected | skipped: the dry run made before the write (Google validateOnly, or the metadata check)
    validation: Mapped[dict | None] = mapped_column(JSONB)
    baseline: Mapped[dict | None] = mapped_column(JSONB)  # ranking measured before the change
    outcome: Mapped[dict | None] = mapped_column(JSONB)  # the 28-day evaluation: observed movement, never "caused by"


class AgentActionApproval(IdMixin, Base):
    """One authorisation for ONE action and ONE exact value. `scope` holds what it covers (action type, field, location, the value, the Google value it was
    judged against, the facts it relied on); the executor refuses it the moment any of those differ. It authorises nothing else, ever."""

    __tablename__ = "agent_action_approvals"
    __table_args__ = (CheckConstraint("decision in ('approved','rejected','auto_authorized')", name="ck_agent_approval_decision"),
                      Index("ix_agent_approvals_action", "action_id", "decided_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_actions.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(16))
    basis: Mapped[str] = mapped_column(String(24))  # owner | admin | level1_policy | preauthorization
    authorized_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    scope_hash: Mapped[str] = mapped_column(String(64))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class AgentInterventionEvent(IdMixin, Base):
    """The append-only history. Each row carries the hash of the previous row of the same action, so any edit, deletion or reordering is detectable
    (executor.verify_history). The database also refuses UPDATE and DELETE on this table (trigger + no privilege); only deleting the whole business may remove it."""

    __tablename__ = "agent_intervention_events"
    __table_args__ = (UniqueConstraint("action_id", "seq", name="uq_agent_event_seq"), Index("ix_agent_events_tenant", "tenant_id", "created_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_actions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(8))  # agent | user | system | google
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRankFollowup(IdMixin, Base):
    """A scheduled re-measurement of the keywords measured before an action (day 7, 14 and 28 after it was verified)."""

    __tablename__ = "agent_rank_followups"
    __table_args__ = (UniqueConstraint("action_id", "day_offset", name="uq_agent_followup"), Index("ix_agent_followups_due", "status", "due_at"),
                      CheckConstraint("status in ('pending','done','deferred','skipped')", name="ck_agent_followup_status"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_actions.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    day_offset: Mapped[int] = mapped_column(SmallInteger)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)


class ConsentGrant(IdMixin, Base):
    """An owner's express consent for ONE kind of automated action at ONE location (Milestone 2, decision D2). Google's API policy: you "must not automate or
    trigger review replies, Q&As, listing creations, listing edits, or other actions without the user's prior specific and express consent".

    A grant is the ONLY thing that lets FlowQr act without a person approving the individual change, and it is narrow: one location, one action type. It stores
    exactly what the owner was shown (`wording_text`, `wording_version`), who agreed and when, and, if withdrawn, who withdrew it and when. The row is never edited
    or deleted (a database trigger refuses both) except to record the revocation; a new grant after a revocation is a new row, so the history of consent is complete.
    Nothing here can authorise a Level 3 action, or the publishing of public content (posts, photos, AI-drafted replies): those stay with a person every time."""

    __tablename__ = "consent_grants"
    __table_args__ = (
        Index("uq_consent_active", "google_location_id", "scope", unique=True, postgresql_where=text("revoked_at is null")),
        Index("ix_consent_tenant", "tenant_id", "granted_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(40))  # an action type from autonomy_policy.SPECS (Level 1-2, not person_only), or "reply_template"
    wording_version: Mapped[str] = mapped_column(String(24))
    wording_text: Mapped[str] = mapped_column(Text)  # exactly what the owner was shown when agreeing
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(16), default="owner_ui")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_reason: Mapped[str | None] = mapped_column(Text)


class PlatformControl(Base):
    """Platform-wide switches an operator can flip at runtime without a deploy (today: the autonomy emergency stop). Not tenant-scoped."""

    __tablename__ = "platform_controls"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
