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
    base_url: str | None = None
    released_at: datetime | None = None


class AssignIn(BaseModel):
    tenant_id: uuid.UUID
    location_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=120)
    confirm: bool = False  # required to change a card that is already in use
    activate: bool = False  # go live now instead of on the first real scan


class TenantAssignIn(BaseModel):
    location_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=120)
    confirm: bool = False
    activate: bool = True


class LookupIn(BaseModel):
    scan: str = Field(min_length=1, max_length=600)  # a scanned link, a token or a printed serial


class BulkAssignIn(BaseModel):
    card_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    serials: list[str] = Field(default_factory=list, max_length=500)
    tenant_id: uuid.UUID
    location_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    confirm: bool = False
    activate: bool = True


class ReserveIn(BaseModel):
    tenant_id: uuid.UUID


class ConfirmIn(BaseModel):
    confirm: bool = False


class StatusIn(BaseModel):
    status: CardStatus


class CardPatchIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    location_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    clear_campaign: bool = False  # open the plain card page again instead of a campaign
    confirm: bool = False


class CardOut(ORM):
    id: uuid.UUID
    card_code: str
    status: CardStatus
    batch_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    location_id: uuid.UUID | None
    label: str | None
    assigned_at: datetime | None
    url: str  # what the printed QR encodes
    nfc_url: str | None = None  # what to write on the NFC tag
    campaign_id: uuid.UUID | None = None
    campaign_name: str | None = None
    batch_name: str | None = None
    public_token: str | None = None
    tenant_name: str | None = None
    location_name: str | None = None
    stats: dict[str, int] = {}
    last_scan_at: datetime | None = None  # most recent human QR scan / NFC tap (bots excluded)


class TrackEventIn(BaseModel):
    type: str
    channel: str | None = None

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in {"landing_view", "copy", "google_click", "ai_assist"}:
            raise ValueError("Unsupported event")
        return v

    @field_validator("channel")
    @classmethod
    def _c(cls, v):
        if v is not None and v not in {"qr", "nfc"}:
            raise ValueError("Unsupported channel")
        return v
