"""Growth agent: knowledge base, tasks with a state machine, scheduled posts, Google snapshots, health history.

Every row is tenant-scoped (RLS). Nothing in here talks to Google: state changes that mean "done on Google" are only written by
code that has just received Google's confirmation.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin

TASK_STATUSES = ("suggested", "drafted", "awaiting_approval", "approved", "scheduled", "published", "failed", "snoozed", "dismissed", "done")
POST_STATUSES = ("draft", "awaiting_approval", "approved", "scheduled", "publishing", "published", "failed", "canceled")


class BusinessKnowledge(IdMixin, TimestampMixin, Base):
    """What the AI may say about this business. The description and service list live in tenants.review_context (one source of truth
    shared with the review assistant); everything else is here."""

    __tablename__ = "business_knowledge"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_business_knowledge_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    offers: Mapped[list] = mapped_column(JSONB, default=list)  # verified prices and offers: [{name, price_inr, details, valid_until}]
    hours: Mapped[str | None] = mapped_column(Text)
    faqs: Mapped[list] = mapped_column(JSONB, default=list)  # [{q, a}]
    brand_voice: Mapped[str | None] = mapped_column(Text)
    approved_claims: Mapped[list] = mapped_column(JSONB, default=list)
    prohibited_claims: Mapped[list] = mapped_column(JSONB, default=list)
    safety_profile: Mapped[str] = mapped_column(String(16), default="general")  # general | health
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AgentSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_agent_settings_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    daily_plan: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_draft_replies: Mapped[bool] = mapped_column(Boolean, default=False)  # drafts only: publishing always needs a person
    last_plan_date: Mapped[date | None] = mapped_column(Date)


class AgentTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        CheckConstraint("status in ('suggested','drafted','awaiting_approval','approved','scheduled','published','failed','snoozed','dismissed','done')", name="ck_agent_task_status"),
        Index("ix_agent_tasks_tenant_status", "tenant_id", "status"),
        Index("uq_agent_tasks_open_dedupe", "tenant_id", "dedupe_key", unique=True, postgresql_where=text("status not in ('published','done','dismissed')")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32))  # reply_review | create_post | profile_fix | add_photo | connect_google | complete_knowledge
    title: Mapped[str] = mapped_column(String(200))
    why: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)  # the real numbers/ids this task is based on
    suggested_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    draft: Mapped[dict | None] = mapped_column(JSONB)  # AI/owner-edited content waiting for approval (never published as is)
    ref_type: Mapped[str | None] = mapped_column(String(24))  # reply_draft | scheduled_post
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    dedupe_key: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(SmallInteger, default=50)  # lower = more urgent
    plan_date: Mapped[date] = mapped_column(Date)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class AgentTaskEvent(IdMixin, Base):
    """Append-only history of a task's state changes (who, when, why)."""

    __tablename__ = "agent_task_events"
    __table_args__ = (Index("ix_agent_task_events_task", "task_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(16))  # agent | user | system | google
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class AgentRun(IdMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_tenant_started", "tenant_id", "started_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # daily_plan | refresh_google | publish_posts | draft_replies
    status: Mapped[str] = mapped_column(String(12))  # running | ok | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class ScheduledPost(IdMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        CheckConstraint("status in ('draft','awaiting_approval','approved','scheduled','publishing','published','failed','canceled')", name="ck_scheduled_post_status"),
        Index("ix_scheduled_posts_due", "status", "scheduled_for"),
        Index("ix_scheduled_posts_tenant", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    summary: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    cta_type: Mapped[str | None] = mapped_column(String(16))
    cta_url: Mapped[str | None] = mapped_column(String(500))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set only after Google returned the post
    google_post_name: Mapped[str | None] = mapped_column(String(300))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GbpSnapshot(IdMixin, TimestampMixin, Base):
    """The last thing Google told us about a location (profile, posts, media, performance). Health and the plan are computed from
    this, so they only ever reflect real responses; `error` says why a refresh failed."""

    __tablename__ = "gbp_snapshots"
    __table_args__ = (UniqueConstraint("google_location_id", name="uq_gbp_snapshot_location"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    info: Mapped[dict | None] = mapped_column(JSONB)
    posts: Mapped[list | None] = mapped_column(JSONB)
    media: Mapped[list | None] = mapped_column(JSONB)
    performance: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class HealthSnapshot(IdMixin, Base):
    __tablename__ = "health_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "day", name="uq_health_snapshot_day"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    breakdown: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
