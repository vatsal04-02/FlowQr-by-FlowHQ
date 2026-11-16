import uuid

from pydantic import BaseModel, ConfigDict, Field


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class SupportIn(BaseModel):
    status: str = Field(pattern="^(none|open|waiting|resolved)$")
    note: str | None = Field(default=None, max_length=2000)


class GeoLimitsIn(BaseModel):
    max_grids: int | None = Field(default=None, ge=1, le=100)
    max_points: int | None = Field(default=None, ge=1, le=200)
    monthly_points: int | None = Field(default=None, ge=1, le=1_000_000)


class PlanLimitsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geo: GeoLimitsIn
    apply_to_existing: bool = False
    note: str = Field(min_length=3, max_length=300)


class SubscriptionAdminIn(BaseModel):
    plan: str | None = Field(default=None, pattern="^[a-z_]{3,32}$")
    status: str | None = Field(default=None, pattern="^(trialing|active|manual|expired|canceled)$")
    extend_trial_days: int | None = Field(default=None, ge=1, le=365)
    note: str = Field(min_length=3, max_length=300)


class CardOrderAdminIn(BaseModel):
    status: str = Field(pattern="^(processing|shipped|cancelled)$")
    tracking_note: str | None = Field(default=None, max_length=500)


class UserActiveIn(BaseModel):
    is_active: bool


class BudgetsIn(BaseModel):
    """Per-business spending ceilings set by a platform admin. A field left out is not changed; null clears it (the business then follows the platform default)."""

    model_config = ConfigDict(extra="forbid")
    ai_monthly_budget_usd: float | None = Field(default=None, ge=0, le=100000)
    places_monthly_cap: int | None = Field(default=None, ge=0, le=1_000_000)
    note: str = Field(min_length=3, max_length=300)
