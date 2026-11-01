import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORM, normalize_phone, validate_google_review_url


class LocationIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    phone: str | None = None
    review_url: str | None = None

    _phone = field_validator("phone")(lambda v: normalize_phone(v))
    _url = field_validator("review_url")(lambda v: validate_google_review_url(v))


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    phone: str | None = None
    review_url: str | None = None
    is_active: bool | None = None

    _phone = field_validator("phone")(lambda v: normalize_phone(v))
    _url = field_validator("review_url")(lambda v: validate_google_review_url(v))


class LocationOut(ORM):
    id: uuid.UUID
    name: str
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    phone: str | None
    review_url: str | None
    review_url_source: str
    is_active: bool
