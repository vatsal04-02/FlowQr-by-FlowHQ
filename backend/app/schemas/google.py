import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class GoogleLocationOut(ORM):
    id: uuid.UUID
    connection_id: uuid.UUID
    location_id: uuid.UUID | None
    google_account_name: str
    google_location_name: str
    title: str | None
    address: str | None
    selected: bool
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None


class ConnectionOut(ORM):
    id: uuid.UUID
    google_email: str | None
    status: str
    last_error: str | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    api_access: str = "unknown"  # unknown | approved | awaiting_approval
    api_access_checked_at: datetime | None = None
    locations_found: int = 0  # Business Profile locations Google listed for this account
    no_locations: bool = False  # signed in and API access works, but the account manages no location: NOT a working business connection


class SelectionItem(BaseModel):
    google_location_id: uuid.UUID
    selected: bool = True
    location_id: uuid.UUID | None = None  # map to an existing FlowQR location
    create_location: bool = False  # or create one from the Google data


class SelectionIn(BaseModel):
    selections: list[SelectionItem] = Field(min_length=1, max_length=200)
