import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
CTA = {"LEARN_MORE", "BOOK", "ORDER", "SHOP", "SIGN_UP", "CALL"}
MEDIA_CATEGORIES = {"COVER", "PROFILE", "LOGO", "EXTERIOR", "INTERIOR", "PRODUCT", "AT_WORK", "FOOD_AND_DRINK", "TEAMS", "ADDITIONAL"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class HoursPeriod(BaseModel):
    day: str
    open: str
    close: str

    @field_validator("day")
    @classmethod
    def _day(cls, v):
        if v not in DAYS:
            raise ValueError("day must be MONDAY..SUNDAY")
        return v

    @model_validator(mode="after")
    def _order(self):
        if not _TIME.match(self.open) or not _TIME.match(self.close):
            raise ValueError("Times must be HH:MM (24-hour)")
        if self.close <= self.open:
            raise ValueError("Closing time must be after opening time (split overnight hours across two days)")
        return self


class LocationInfoUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=750)
    hours: list[HoursPeriod] | None = Field(default=None, max_length=28)
    primary_category: str | None = Field(default=None, pattern=r"^categories/gcid:[a-z0-9_]+$")
    additional_categories: list[str] | None = Field(default=None, max_length=9)
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=300)

    @field_validator("website")
    @classmethod
    def _site(cls, v):
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Website must start with http:// or https://")
        return v

    @field_validator("additional_categories")
    @classmethod
    def _cats(cls, v):
        if v and not all(re.match(r"^categories/gcid:[a-z0-9_]+$", c) for c in v):
            raise ValueError("Invalid category id")
        return v


class PostIn(BaseModel):
    summary: str = Field(min_length=10, max_length=1500)
    language: str = Field(default="en", pattern="^(en|hi)$")
    cta_type: str | None = None
    cta_url: str | None = Field(default=None, max_length=500)
    photo_url: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _cta(self):
        if self.cta_type and self.cta_type not in CTA:
            raise ValueError("Unsupported call-to-action")
        if self.cta_type and self.cta_type != "CALL" and not (self.cta_url or "").startswith("https://"):
            raise ValueError("This button needs an https:// link")
        if self.photo_url and not self.photo_url.startswith("https://"):
            raise ValueError("Photo link must be https://")
        return self


class MediaIn(BaseModel):
    source_url: str = Field(max_length=500)
    category: str = "ADDITIONAL"

    @model_validator(mode="after")
    def _v(self):
        if not self.source_url.startswith("https://"):
            raise ValueError("Photo link must be a public https:// URL")
        if self.category not in MEDIA_CATEGORIES:
            raise ValueError("Unsupported photo category")
        return self
