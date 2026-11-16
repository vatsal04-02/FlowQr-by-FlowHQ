import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.schemas.common import validate_google_review_url
from app.schemas.qr import QRStyleIn
from app.services.ai.review_generate import LANGUAGES, STYLES, clean_field
from app.services.review_suggestions import CATALOG, MAX_DESCRIPTION, check_plain, clean_services

Style = Literal["natural", "short", "detailed", "professional", "warm"]
Language = Literal["en", "hi"]
Background = Literal["plain", "soft", "gradient", "dots"]
Status = Literal["active", "paused", "archived"]


class Customization(BaseModel):
    """Per-campaign look and generator defaults. Every field has a default, so old/empty rows always validate."""

    brand_color: str = Field(default="#1B46B8", pattern=r"^#[0-9A-Fa-f]{6}$")
    display_name: str | None = Field(default=None, max_length=120)
    logo_url: str | None = Field(default=None, max_length=500)
    welcome_message: str | None = Field(default=None, max_length=200)
    footer_message: str | None = Field(default=None, max_length=200)
    background: Background = "soft"
    show_rating: bool = True
    default_style: Style = "natural"
    default_language: Language = "en"
    allowed_styles: list[Style] = Field(default_factory=lambda: list(STYLES), min_length=1)

    @field_validator("display_name", "welcome_message", "footer_message")
    @classmethod
    def _text(cls, v):
        return clean_field(v, 200) or None

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("Logo URL must be https")
        return v or None

    @field_validator("brand_color")
    @classmethod
    def _color(cls, v):
        return v.upper()

    @model_validator(mode="after")
    def _default_allowed(self):
        if self.default_style not in self.allowed_styles:
            self.allowed_styles = [self.default_style, *self.allowed_styles]
        return self


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    location_id: uuid.UUID
    customization: Customization | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return clean_field(v, 120)


class CampaignPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    location_id: uuid.UUID | None = None
    status: Status | None = None
    customization: Customization | None = None
    qr_style: QRStyleIn | None = None  # how this campaign's code is drawn; send null to go back to the business's style

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return clean_field(v, 120) if v else v


class DeactivateCodeIn(BaseModel):
    """Switching off an earlier code stops every printed copy of it, so it must be asked for in so many words."""

    confirm: Literal["DEACTIVATE"]


class OldCode(BaseModel):
    public_id: str
    url: str
    retired_at: datetime
    active: bool  # False = deliberately deactivated; scanning it shows "switched off"
    deactivated_at: datetime | None = None


class CampaignStats(BaseModel):
    scans: int = 0
    unique_scans: int = 0  # distinct devices per day
    feedback_submitted: int = 0  # "started a review": either asked for AI help or chose to write it themselves
    ai_requested: int = 0
    manual_selected: int = 0
    drafts_generated: int = 0
    drafts_approved: int = 0
    google_redirects: int = 0


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: Status
    location_id: uuid.UUID | None
    location_name: str | None
    public_id: str
    url: str
    customization: Customization
    review_url_ready: bool
    review_url_source: str | None
    stats: CampaignStats
    created_at: datetime
    updated_at: datetime
    qr_rotated_at: datetime | None = None
    qr_style: QRStyleIn | None = None  # None = uses the business's QR style
    retired_codes: int = 0  # how many earlier codes this campaign has
    old_codes: list[OldCode] = []  # earlier codes; they keep opening this campaign unless deactivated


class ReviewUrlIn(BaseModel):
    url: str | None = None  # a Google review link, entered by an admin
    use_google: bool = False  # or: take the link from the connected Business Profile location

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return validate_google_review_url(v)

    @model_validator(mode="after")
    def _one(self):
        if bool(self.url) == bool(self.use_google):
            raise ValueError("Provide either a review link or use_google, not both")
        return self


# ---------- public (customer) ----------
class GenerateIn(BaseModel):
    """Start a customer session. `text` is the single free-text box (keywords, a sentence or a whole review).
    mode "ai" asks for a draft (needs some words); mode "manual" only opens a session for a review the customer writes themselves
    (no AI call, words optional). The three structured fields are the previous multi-question form, still accepted."""

    text: str | None = Field(default=None, max_length=1200)
    mode: Literal["ai", "manual"] = "ai"
    suggestions: list[str] = Field(default_factory=list, max_length=8)  # ids of the topic chips the customer picked (topics, not claims)
    sentiment: Literal["good", "okay", "not_good"] | None = None  # what they think of those topics; optional if they also write something
    service: str | None = Field(default=None, max_length=300)
    appreciated: str | None = Field(default=None, max_length=500)
    details: str | None = Field(default=None, max_length=600)
    rating: int | None = Field(default=None, ge=1, le=5)
    language: Language = "en"
    style: Style | None = None

    @field_validator("suggestions")
    @classmethod
    def _ids(cls, v):
        if any(not re.fullmatch(r"[a-z_]{2,40}", s) for s in v):
            raise ValueError("Unknown topic.")
        return v

    @model_validator(mode="after")
    def _content(self):
        total = sum(len(p) for p in (clean_field(self.text, 1200), clean_field(self.service, 300), clean_field(self.appreciated, 500), clean_field(self.details, 600)))
        if self.mode == "ai" and self.rating is None:  # the stars set the direction of an AI draft; writing it yourself never needs them
            raise ValueError("Choose a star rating first so the review reflects how your visit was.")
        if self.mode == "ai" and total < 1 and not self.suggestions:  # nothing typed or picked: never generate. One or two characters ("ok") get the friendly follow-up instead
            raise ValueError("Pick at least one thing that applies, or write a few words about your visit first.")
        if total > settings.public_ai_max_input_chars:
            raise ValueError(f"Please keep it under {settings.public_ai_max_input_chars} characters.")
        return self


class ContextIn(BaseModel):
    """Owner-edited business context. It tells the AI what the business OFFERS (never what a customer experienced), so anything that
    reads like a claim, a price or a link is refused."""

    category_key: str | None = None  # None = detect from the business category set in Settings
    description: str | None = Field(default=None, max_length=600)
    services: list[str] = Field(default_factory=list, max_length=30)
    disabled_suggestions: list[str] = Field(default_factory=list, max_length=30)
    languages: list[Language] = Field(default_factory=lambda: ["en", "hi"], min_length=1, max_length=2)

    @field_validator("category_key")
    @classmethod
    def _cat(cls, v):
        if v is not None and v not in CATALOG:
            raise ValueError("Unknown category.")
        return v

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        v = clean_field(v, 10_000)  # not truncated here: too long is an error, not something to silently cut
        if len(v) > MAX_DESCRIPTION:
            raise ValueError(f"Keep the description under {MAX_DESCRIPTION} characters.")
        return check_plain(v, "Description") if v else ""

    @field_validator("services")
    @classmethod
    def _svc(cls, v):
        return clean_services(v)

    @field_validator("disabled_suggestions")
    @classmethod
    def _dis(cls, v):
        return sorted({s for s in v if re.fullmatch(r"[a-z_]{2,40}", s)})

    @field_validator("languages")
    @classmethod
    def _langs(cls, v):
        return list(dict.fromkeys(v))


class AITestIn(BaseModel):
    """Admin 'test the model' request. The default is a realistic sample so one click works."""

    text: str | None = Field(default="back pain, friendly staff, explained exercises clearly", max_length=1200)
    rating: int | None = Field(default=None, ge=1, le=5)
    language: Language = "en"
    style: Style = "natural"

    @model_validator(mode="after")
    def _content(self):
        if len(clean_field(self.text, 1200)) < 3:
            raise ValueError("Enter some sample words to test with.")
        return self


class RegenerateIn(BaseModel):
    session_id: str = Field(min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    style: Style | None = None
    language: Language | None = None


class ApproveIn(BaseModel):
    session_id: str = Field(min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    final_text: str = Field(min_length=10, max_length=2000)

    @field_validator("final_text")
    @classmethod
    def _text(cls, v):
        v = clean_field(v, 2000)
        if len(v) < 10:
            raise ValueError("Please write at least a short sentence")
        return v


class RedirectIn(BaseModel):
    session_id: str = Field(min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    copied: bool | None = None  # did the browser copy the review before Google opened? (a bare yes/no; never any text)


class HandoffIn(BaseModel):
    """The one tap on "Copy & Continue to Google", reported in a single request (sent with keepalive, so it completes even if the page is
    backgrounded or closed): confirm the customer's final wording, and count the Google tap. A session is opened here if they never asked for AI help."""

    session_id: str | None = Field(default=None, min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    final_text: str = Field(min_length=10, max_length=2000)
    copied: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    suggestions: list[str] = Field(default_factory=list, max_length=8)
    language: Language = "en"

    @field_validator("final_text")
    @classmethod
    def _text(cls, v):
        v = clean_field(v, 2000)
        if len(v) < 10:
            raise ValueError("Please write at least a short sentence")
        return v

    @field_validator("suggestions")
    @classmethod
    def _ids(cls, v):
        if any(not re.fullmatch(r"[a-z_]{2,40}", s) for s in v):
            raise ValueError("Unknown topic.")
        return v


class SubmitIn(BaseModel):
    """Direct submission (only when an approved provider is enabled; today it never is). The customer's explicit consent to submit THIS text, with their
    own rating, is required and recorded. The rating is accepted as given: it never changes whether a customer may submit."""

    session_id: str | None = Field(default=None, min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    final_text: str = Field(min_length=10, max_length=2000)
    rating: int = Field(ge=1, le=5)
    consent: bool
    suggestions: list[str] = Field(default_factory=list, max_length=8)
    language: Language = "en"

    @field_validator("final_text")
    @classmethod
    def _text(cls, v):
        v = clean_field(v, 2000)
        if len(v) < 10:
            raise ValueError("Please write at least a short sentence")
        return v

    @field_validator("suggestions")
    @classmethod
    def _ids(cls, v):
        if any(not re.fullmatch(r"[a-z_]{2,40}", s) for s in v):
            raise ValueError("Unknown topic.")
        return v

    @model_validator(mode="after")
    def _consent(self):
        if self.consent is not True:
            raise ValueError("Please confirm that this review reflects your own experience.")
        return self


class RefineIn(BaseModel):
    """Update an existing session's stars, topics and words and rewrite the draft. The page protects the customer's own edits (it asks first);
    the server only ever rewrites from what the customer picked and typed."""

    session_id: str = Field(min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    rating: int = Field(ge=1, le=5)
    suggestions: list[str] = Field(default_factory=list, max_length=8)
    text: str | None = Field(default=None, max_length=1200)
    language: Language | None = None

    @field_validator("suggestions")
    @classmethod
    def _ids(cls, v):
        if any(not re.fullmatch(r"[a-z_]{2,40}", s) for s in v):
            raise ValueError("Unknown topic.")
        return v

    @model_validator(mode="after")
    def _content(self):
        if not self.suggestions and len(clean_field(self.text, 1200)) < 1:
            raise ValueError("Pick at least one thing that applies, or write a few words first.")
        return self
