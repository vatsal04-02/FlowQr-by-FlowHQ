"""Request shapes for the website builder. Everything is strict (unknown fields refused); the website CONTENT itself is validated by services/sites/content.py, which is the single place that knows
every field's type and limit."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteCreateIn(_Strict):
    template_key: str | None = Field(default=None, max_length=24)
    site_slug: str | None = Field(default=None, max_length=40)
    commercial_status: Literal["complimentary", "paid_offline"]
    commercial_reason: str | None = Field(default=None, max_length=300)
    billing_period: Literal["monthly", "annual"] | None = None
    paid_until: date | None = None


class SiteContentIn(_Strict):
    content: dict
    base_version: int = Field(ge=1)


class TemplateIn(_Strict):
    template_key: str = Field(max_length=24)


class SlugIn(_Strict):
    site_slug: str = Field(max_length=40)


class PublishIn(_Strict):
    note: str | None = Field(default=None, max_length=200)


class ReasonIn(_Strict):
    reason: str = Field(min_length=5, max_length=300)


class CommercialIn(_Strict):
    status: Literal["complimentary", "paid_offline", "expired", "suspended"]
    reason: str | None = Field(default=None, max_length=300)
    billing_period: Literal["monthly", "annual"] | None = None
    paid_until: date | None = None


class RollbackIn(_Strict):
    revision: int = Field(ge=1)


class AssetPatchIn(_Strict):
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class EnquiryStatusIn(_Strict):
    status: Literal["new", "contacted", "resolved", "spam"]


class EnquiryPublicIn(_Strict):
    """What the hosting Worker forwards. `client_ip` is trusted only because the call carries the service token."""
    host: str = Field(max_length=253)
    name: str = Field(default="", max_length=400)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=400)
    message: str = Field(default="", max_length=4000)
    consent: bool = False
    whatsapp_ok: bool = False  # the visitor ticked "updates on WhatsApp": their own consent to utility messages about this enquiry (recorded by services/whatsapp)
    website: str = Field(default="", max_length=200)  # honeypot
    client_ip: str | None = Field(default=None, max_length=64)
