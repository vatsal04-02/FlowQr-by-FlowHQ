"""What happened to each AI-written output: kept as is, edited, or thrown away. Feeds the AI Output Acceptance Rate (services/ai/outcomes.py).

Only owner-facing business text is stored (reply drafts, posts, profile descriptions). Customer review drafts are measured from review_drafts
rows instead and never copied here."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, utcnow


class AIOutput(IdMixin, Base):
    __tablename__ = "ai_outputs"
    __table_args__ = (UniqueConstraint("kind", "ref_id", name="uq_ai_output_ref"), Index("ix_ai_outputs_tenant_kind", "tenant_id", "kind", "created_at"),
                      CheckConstraint("kind in ('reply','post','description')", name="ck_ai_output_kind"),
                      CheckConstraint("decision is null or decision in ('approved','rejected','replaced')", name="ck_ai_output_decision"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    ref_id: Mapped[uuid.UUID] = mapped_column()
    model: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(8))
    original_text: Mapped[str] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(12))
    edit_ratio: Mapped[float | None] = mapped_column(Float)
    reject_reason: Mapped[str | None] = mapped_column(String(40))
