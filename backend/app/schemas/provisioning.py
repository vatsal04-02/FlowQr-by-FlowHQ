"""Input shapes for the admin business directory. Every text field is trimmed and length-limited; the phone is normalised; the review link must be a secure Google link; an email, when given, must be valid."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import normalize_phone, validate_google_review_url
from app.services import registration


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _email(v: str | None) -> str | None:
    v = _clean(v)
    if v is None:
        return None
    n = registration.normalize_email(v)
    if not n:
        raise ValueError("Enter a valid email address")
    return v.lower()


def _website(v: str | None) -> str | None:
    v = _clean(v)
    if v is None:
        return None
    if not re.match(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?$", v):
        raise ValueError("The website must be a secure https:// address")
    return v


class AgreementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["phone", "in_person", "whatsapp", "paper", "other"]
    note: str | None = Field(default=None, max_length=300)
    confirm: bool = False  # the administrator's own confirmation that the business was taken through the terms

    @model_validator(mode="after")
    def _confirmed(self):
        if not self.confirm:
            raise ValueError("Confirm that you took the business through the terms")
        self.note = _clean(self.note)
        return self


class AdminBusinessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    location_name: str | None = Field(default=None, max_length=200)
    review_url: str | None = Field(default=None, max_length=1000)
    website: str | None = Field(default=None, max_length=300)
    agreement: AgreementIn | None = None
    duplicate_reason: str | None = Field(default=None, max_length=300)

    @field_validator("name", "category", "contact_name", "address", "city", "location_name", "duplicate_reason")
    @classmethod
    def _trim(cls, v):
        return _clean(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        n = normalize_phone(v)
        if not n:
            raise ValueError("Enter the shop's phone number")
        return n

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        return _email(v)

    @field_validator("website")
    @classmethod
    def _w(cls, v):
        return _website(v)

    @field_validator("review_url")
    @classmethod
    def _r(cls, v):
        return validate_google_review_url(v)

    @field_validator("duplicate_reason")
    @classmethod
    def _dr(cls, v):
        if v is not None and len(v) < 10:
            raise ValueError("Say why this is a different business (at least 10 characters)")
        return v


class DuplicateCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    review_url: str | None = Field(default=None, max_length=1000)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        try:
            return normalize_phone(v)
        except ValueError:
            return None

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        try:
            return _email(v)
        except ValueError:
            return None

    @field_validator("review_url")
    @classmethod
    def _r(cls, v):
        try:
            return validate_google_review_url(v)
        except ValueError:
            return None


class BusinessPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)

    @field_validator("name", "category", "contact_name", "address")
    @classmethod
    def _trim(cls, v):
        return _clean(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if _clean(v) else None

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        return _email(v)

    @field_validator("website")
    @classmethod
    def _w(cls, v):
        return _website(v)


class LocationAdminIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    review_url: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "address_line", "city")
    @classmethod
    def _trim(cls, v):
        return _clean(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if _clean(v) else None

    @field_validator("review_url")
    @classmethod
    def _r(cls, v):
        return validate_google_review_url(v)


class LocationAdminPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    review_url: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    confirm: bool = False

    @field_validator("name", "address_line", "city")
    @classmethod
    def _trim(cls, v):
        return _clean(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if _clean(v) else None

    @field_validator("review_url")
    @classmethod
    def _r(cls, v):
        return validate_google_review_url(v)


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    delivery: Literal["email", "link"]

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        r = _email(v)
        if not r:
            raise ValueError("Enter the shopkeeper's email address")
        return r


class ManagedAccessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["revoke", "restore"]
    note: str = Field(min_length=3, max_length=300)


class ClaimRevokeIn(BaseModel):
    """Revoking a claim never touches the sign-up allowlist unless this is set, and then only when nothing else needs the address (services/provisioning.py)."""
    model_config = ConfigDict(extra="forbid")
    remove_from_allowlist: bool = False


class DataRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["export", "deletion"]
    requester_name: str = Field(min_length=2, max_length=120)
    requester_role: Literal["owner", "representative", "other"]
    received_via: Literal["phone", "in_person", "whatsapp", "email", "paper", "other"]
    requester_contact: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("requester_name", "requester_contact", "note")
    @classmethod
    def _trim(cls, v):
        return _clean(v)


class DataRequestVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["callback_to_shop_phone", "in_person_at_shop", "whatsapp_from_shop_phone", "email_from_known_address", "other"]
    contacted_on: str | None = Field(default=None, max_length=254)  # the number or address actually used; must be the one on the business record for the methods that use one
    note: str | None = Field(default=None, max_length=300)
    confirm: bool = False

    @field_validator("contacted_on", "note")
    @classmethod
    def _trim(cls, v):
        return _clean(v)

    @model_validator(mode="after")
    def _ok(self):
        if not self.confirm:
            raise ValueError("Confirm that you checked who is asking")
        if self.method == "other" and not self.note:
            raise ValueError("Describe how you verified them")
        return self


class DataRequestReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=300)

    @field_validator("reason")
    @classmethod
    def _trim(cls, v):
        return _clean(v) or ""


class DataRequestDeliveredIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery: Literal["handed_over_in_person", "emailed_to_verified_address", "sent_on_whatsapp_to_verified_number", "other"]
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note")
    @classmethod
    def _trim(cls, v):
        return _clean(v)


class DataRequestExecuteIn(BaseModel):
    """The three things a permanent deletion needs from the administrator: WHY (recorded), the business name typed exactly, and an explicit final confirmation."""
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=300)
    confirm_name: str = Field(min_length=1, max_length=200)
    acknowledge: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        v = _clean(v) or ""
        if len(v) < 10:
            raise ValueError("Say why this business is being deleted (at least 10 characters)")
        return v
