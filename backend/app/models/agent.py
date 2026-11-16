"""Growth agent: knowledge base, tasks with a state machine, scheduled posts, Google snapshots, health history.

Every row is tenant-scoped (RLS). Nothing in here talks to Google: state changes that mean "done on Google" are only written by
code that has just received Google's confirmation.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow

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
    audience: Mapped[str | None] = mapped_column(Text)  # who the owner wants to reach: "office workers nearby", "parents of school children"
    safety_profile: Mapped[str] = mapped_column(String(16), default="general")  # general | health
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AgentSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_agent_settings_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    daily_plan: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_draft_replies: Mapped[bool] = mapped_column(Boolean, default=False)  # drafts only: publishing always needs a person
    # One AI post draft per selected location per day, waiting for approval (never published without a person). Off by default.
    auto_draft_posts: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_plan_date: Mapped[date | None] = mapped_column(Date)
    # Balanced Autonomy (migration 0027). ON by default since migration 0031 (owner decision 2026-11-15) with an off switch; Level 3 actions can never be pre-authorised.
    autonomy_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    autonomy_permissions: Mapped[dict] = mapped_column(JSONB, default=dict)  # {action_type: "auto" | "ask" | "off"}: a pre-authorisation is one specific type set to "auto"
    autonomy_permissions_by: Mapped[uuid.UUID | None] = mapped_column()
    autonomy_permissions_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    autonomy_daily_limit: Mapped[int] = mapped_column(Integer, default=3, server_default="3")  # autonomous executions per 24 h
    autonomy_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    autonomy_suspended_reason: Mapped[str | None] = mapped_column(Text)
    autonomy_failure_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Template-based automatic replies to positive reviews (migration 0031). ON by default, with an off switch. Only reviews newer than `auto_reply_since` are ever answered.
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    auto_reply_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text("now()"))
    auto_reply_min_rating: Mapped[int] = mapped_column(SmallInteger, default=4, server_default="4")
    auto_reply_daily_limit: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    reply_templates: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))  # the owner's own templates; empty = the built-in set


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
    # Google LocalPostTopicType: STANDARD (update) | OFFER | EVENT. OFFER and EVENT need a title and a full start/end (Google rule).
    topic_type: Mapped[str] = mapped_column(String(16), default="STANDARD", server_default="STANDARD")
    event_title: Mapped[str | None] = mapped_column(String(58))
    event_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_coupon: Mapped[str | None] = mapped_column(String(58))
    offer_url: Mapped[str | None] = mapped_column(String(500))
    offer_terms: Mapped[str | None] = mapped_column(Text)
    visual_hint: Mapped[str | None] = mapped_column(Text)  # AI's suggestion for a photo to pair with the post (text only)
    # Crash-safe publishing (migration 0026): the atomic "publishing" claim is committed BEFORE Google is called; these let a retry or the
    # recovery job tell whether an earlier attempt may already have created the post on Google.
    publishing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_token: Mapped[uuid.UUID | None] = mapped_column()


class ScheduledMedia(IdMixin, TimestampMixin, Base):
    """A photo in FlowQR's library on its way to Google: uploaded -> awaiting_approval -> scheduled -> publishing -> published | failed.

    `published` means Google returned a MediaItem for it (with its resource name). Google may still be processing it, or hold it until
    the profile is verified; that is tracked separately (`google_url` appears once Google serves it). An upload into FlowQR alone is
    never shown as published."""
    __tablename__ = "scheduled_media"
    __table_args__ = (
        CheckConstraint("status in ('awaiting_approval','scheduled','publishing','published','failed','canceled')", name="ck_scheduled_media_status"),
        Index("ix_scheduled_media_due", "status", "scheduled_for"),
        Index("ix_scheduled_media_tenant", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(String(300))
    file_name: Mapped[str | None] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[str] = mapped_column(String(20), default="awaiting_approval")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    google_media_name: Mapped[str | None] = mapped_column(String(300))
    google_url: Mapped[str | None] = mapped_column(String(1000))
    google_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when Google returned the MediaItem
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
