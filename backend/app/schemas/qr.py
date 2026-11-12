import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.qr_style import style_problem

Format = Literal["png", "svg", "pdf"]


class QRStyleIn(BaseModel):
    """How a QR code looks. It can never change what the code encodes, and combinations that would not scan are rejected."""

    dark: str = Field(default="#111827", pattern=r"^#[0-9A-Fa-f]{6}$")  # the modules
    light: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")  # the background
    margin: int = Field(default=4, ge=4, le=16)  # quiet zone in modules; the QR standard's minimum is 4
    error_correction: Literal["L", "M", "Q", "H"] = "H"  # forced to H whenever a logo is drawn
    size_px: int = Field(default=1024, ge=256, le=4096)  # minimum PNG/SVG width; rounded up to whole pixels per module
    use_logo: bool = False
    logo_scale: float = Field(default=0.2, ge=0.1, le=0.25)  # logo width as a fraction of the code
    caption: str | None = Field(default=None, max_length=60)  # printed under the code, outside the quiet zone

    @field_validator("dark", "light")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("caption")
    @classmethod
    def _caption(cls, v):
        v = " ".join((v or "").split())
        if not v:
            return None
        if any(ord(c) < 32 or ord(c) > 255 for c in v):
            raise ValueError("The caption can use Latin letters, digits and punctuation only (the PDF/PNG label font has no other scripts yet)")
        return v

    @model_validator(mode="after")
    def _scannable(self):
        problem = style_problem(self.model_dump())
        if problem:
            raise ValueError(problem)
        return self


class QRStyleOut(BaseModel):
    style: QRStyleIn
    has_logo: bool
    is_default: bool
    verification: Literal["decoded", "rules_only"]  # "decoded": every non-default style is proven by decoding its rendering


class BulkIn(BaseModel):
    card_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    campaign_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    all_cards: bool = False
    all_campaigns: bool = False
    formats: list[Format] = Field(default_factory=lambda: ["png", "svg", "pdf"], min_length=1, max_length=3)
    sheet: bool = True  # also include an A4 print sheet (PDF, 12 codes per page)
    size_px: int | None = Field(default=None, ge=256, le=4096)

    @model_validator(mode="after")
    def _some(self):
        if not (self.card_ids or self.campaign_ids or self.all_cards or self.all_campaigns):
            raise ValueError("Choose at least one card or campaign")
        return self
