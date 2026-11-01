import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.business import ReplyStatus
from app.schemas.common import ORM


class DraftOut(ORM):
    id: uuid.UUID
    review_id: uuid.UUID
    body: str
    status: ReplyStatus
    language: str
    generated_by_ai: bool
    requires_human_handling: bool
    flag_reasons: list
    flag_messages: list[str] = []
    approved_at: datetime | None
    published_at: datetime | None
    failure_reason: str | None
    attempts: int
    created_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    location_id: uuid.UUID | None
    location_name: str | None
    rating: int
    text: str | None
    reviewer_name: str | None
    review_created_at: datetime
    review_updated_at: datetime | None
    update_count: int
    google_reply_text: str | None
    google_reply_at: datetime | None
    reply_state: str  # none | draft | approved | published | failed
    sensitive_reasons: list[str]
    latest_draft: DraftOut | None


class ReviewList(BaseModel):
    total: int
    items: list[ReviewOut]


class DraftBodyIn(BaseModel):
    body: str = Field(min_length=2, max_length=4000)


class ApproveIn(BaseModel):
    acknowledge_flags: bool = False


class LogOut(ORM):
    id: uuid.UUID
    draft_id: uuid.UUID | None
    action: str
    success: bool
    http_status: int | None
    error: str | None
    created_at: datetime


class ReviewDetail(BaseModel):
    review: ReviewOut
    drafts: list[DraftOut]
    logs: list[LogOut]
