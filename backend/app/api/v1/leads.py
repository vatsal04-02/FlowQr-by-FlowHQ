"""Book-a-demo form on the public marketing site. Unauthenticated: validated, rate limited per IP, with a honeypot field.

A filled honeypot gets the same success answer as a real request, so a bot learns nothing, but nothing is stored."""
import hashlib
import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import client_ip, limit_by_ip
from app.models.base import utcnow
from app.models.leads import Lead

router = APIRouter(prefix="/public/leads", tags=["public"])

BUSINESS_TYPES = ("clinic", "dental", "salon", "restaurant", "gym", "coaching", "retail", "hotel", "other")
_PHONE = re.compile(r"^[6-9]\d{9}$")


class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    business_type: Literal["clinic", "dental", "salon", "restaurant", "gym", "coaching", "retail", "hotel", "other"]
    locations: int = Field(ge=1, le=500)
    phone: str
    whatsapp_ok: bool = False
    preferred_time: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=200)  # honeypot: hidden from people, filled by bots

    @field_validator("name", "business_name", "city", "preferred_time")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r"[\s\-()]", "", v)
        digits = digits.removeprefix("+91").removeprefix("0") if len(digits) > 10 else digits
        if not _PHONE.match(digits):
            raise ValueError("Enter a 10-digit Indian mobile number.")
        return "+91" + digits


@router.post("", status_code=201, dependencies=[Depends(limit_by_ip("leads", 5, 3600))])
def create_lead(body: LeadIn, request: Request, db: Session = Depends(public_db)):
    if body.website:
        return {"ok": True}
    ip = client_ip(request)
    db.add(Lead(
        name=body.name, business_name=body.business_name, city=body.city, business_type=body.business_type, locations=body.locations,
        phone=body.phone, whatsapp_ok=body.whatsapp_ok, preferred_time=body.preferred_time or None, source="demo",
        ip_hash=hashlib.sha256(f"{settings.secret_key}:{ip}".encode()).hexdigest() if ip != "unknown" else None, created_at=utcnow(),
    ))
    db.commit()
    return {"ok": True}
