import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.tenancy import Role
from app.schemas.common import ORM, normalize_phone, validate_language, validate_timezone


def _strong(pw: str) -> str:
    if len(pw) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(pw) > 128:
        raise ValueError("Password is too long")
    if pw.strip() != pw or pw.isdigit() or pw.lower() == pw or pw.upper() == pw:
        # require mixed case and not purely numeric; leading/trailing space not allowed
        raise ValueError("Use upper and lower case letters and no leading/trailing spaces")
    return pw


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    # "I confirm that I am 18 years of age or older." Defaults to False (never assumed); the endpoint refuses registration unless it is True. No date of birth is collected.
    age_confirmed: bool = False

    _pw = field_validator("password")(_strong)
    _phone = field_validator("phone")(lambda v: normalize_phone(v))


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str
    _pw = field_validator("new_password")(_strong)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str
    _pw = field_validator("new_password")(_strong)


class SetPasswordIn(BaseModel):
    new_password: str
    _pw = field_validator("new_password")(_strong)


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = None
    _phone = field_validator("phone")(lambda v: normalize_phone(v))


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    is_platform_admin: bool
    email_verified_at: datetime | None = None
    has_local_login: bool = True  # False for Google-only accounts
    google_linked: bool = False


class TenantOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    category: str | None
    email: str | None
    phone: str | None
    address: str | None
    website: str | None
    language: str
    timezone: str
    logo_url: str | None
    brand_tone: str | None
    ai_instructions: str | None
    onboarding_completed: bool
    suspended_at: datetime | None = None
    suspension_reason: str | None = None
    support_status: str = "none"
    review_goal: int | None = None


class MembershipOut(BaseModel):
    tenant: TenantOut
    role: Role


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    active_tenant_id: uuid.UUID | None
    csrf_token: str
    integrations: dict


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=80)
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=300)
    language: str = "en"
    timezone: str = "Asia/Kolkata"

    _phone = field_validator("phone")(lambda v: normalize_phone(v))
    _lang = field_validator("language")(validate_language)
    _tz = field_validator("timezone")(validate_timezone)

    @field_validator("website")
    @classmethod
    def _site(cls, v):
        if v and not v.lower().startswith(("http://", "https://")):
            v = "https://" + v
        return v or None


class TenantUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=300)
    language: str | None = None
    timezone: str | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    brand_tone: str | None = Field(default=None, max_length=300)
    ai_instructions: str | None = Field(default=None, max_length=2000)
    review_goal: int | None = Field(default=None, ge=1, le=100000)

    _phone = field_validator("phone")(lambda v: normalize_phone(v))
    _lang = field_validator("language")(lambda v: v if v is None else validate_language(v))
    _tz = field_validator("timezone")(lambda v: v if v is None else validate_timezone(v))

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("Logo URL must be https")
        return v or None


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.staff
    location_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)  # staff only: limit them to these locations (None = all)


class StaffLocationsIn(BaseModel):
    all_locations: bool
    location_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class InvitationAcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class RoleUpdateIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    all_locations: bool = True  # False => limited to location_ids (staff only; owners and admins always have every location)
    location_ids: list[uuid.UUID] = []


class InvitationOut(ORM):
    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    location_ids: list[uuid.UUID] | None = None
    email_sent: bool | None = None  # False => invitation exists but the email could not be delivered
