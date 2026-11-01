import uuid

from pydantic import BaseModel, Field


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class SupportIn(BaseModel):
    status: str = Field(pattern="^(none|open|waiting|resolved)$")
    note: str | None = Field(default=None, max_length=2000)


class SubscriptionAdminIn(BaseModel):
    plan: str | None = Field(default=None, pattern="^(essential|growth|multi)$")
    status: str | None = Field(default=None, pattern="^(trialing|active|manual|expired|canceled)$")
    extend_trial_days: int | None = Field(default=None, ge=1, le=365)
    note: str = Field(min_length=3, max_length=300)


class CardOrderAdminIn(BaseModel):
    status: str = Field(pattern="^(processing|shipped|cancelled)$")
    tracking_note: str | None = Field(default=None, max_length=500)


class UserActiveIn(BaseModel):
    is_active: bool
