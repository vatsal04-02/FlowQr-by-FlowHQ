import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.cards import CardStatus
from app.schemas.common import ORM


class BatchCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    quantity: int = Field(ge=1, le=2000)
    prefix: str = Field(default="FQR", pattern=r"^[A-Z]{2,6}$")
    notes: str | None = Field(default=None, max_length=1000)


class BatchOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    quantity: int
    created_at: datetime
    notes: str | None


class AssignIn(BaseModel):
    tenant_id: uuid.UUID
    location_id: uuid.UUID
    label: str | None = Field(default=None, max_length=120)


class StatusIn(BaseModel):
    status: CardStatus


class CardPatchIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    location_id: uuid.UUID | None = None


class CardOut(ORM):
    id: uuid.UUID
    card_code: str
    status: CardStatus
    batch_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    location_id: uuid.UUID | None
    label: str | None
    assigned_at: datetime | None
    url: str
    public_token: str | None = None
    tenant_name: str | None = None
    location_name: str | None = None
    stats: dict[str, int] = {}


class TrackEventIn(BaseModel):
    type: str

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in {"landing_view", "copy", "google_click"}:
            raise ValueError("Unsupported event")
        return v
