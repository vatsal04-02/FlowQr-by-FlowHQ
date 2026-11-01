import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM, normalize_phone


class PlanOut(ORM):
    code: str
    name: str
    price_paise: int
    currency: str
    interval: str
    max_locations: int
    monthly_ai_generations: int
    max_staff: int
    features: list[str]


class CheckoutIn(BaseModel):
    plan: str = Field(pattern="^(essential|growth|multi)$")


class VerifySubscriptionIn(BaseModel):
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_subscription_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=10, max_length=200)


class CancelIn(BaseModel):
    at_cycle_end: bool = True


class ChangePlanIn(BaseModel):
    plan: str = Field(pattern="^(essential|growth|multi)$")


class Shipping(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str
    address_line: str = Field(min_length=4, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(pattern=r"^\d{6}$")

    def model_post_init(self, __context) -> None:
        self.phone = normalize_phone(self.phone) or ""


class CardOrderIn(BaseModel):
    quantity: int = Field(ge=1, le=10000)
    shipping: Shipping


class VerifyOrderIn(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=64)
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=10, max_length=200)


class PaymentOut(ORM):
    id: uuid.UUID
    kind: str
    status: str
    amount_paise: int
    currency: str
    razorpay_payment_id: str | None
    razorpay_order_id: str | None
    razorpay_subscription_id: str | None
    razorpay_invoice_id: str | None
    method: str | None
    error_description: str | None
    paid_at: datetime | None
    created_at: datetime


class CardOrderOut(ORM):
    id: uuid.UUID
    quantity: int
    unit_price_paise: int
    amount_paise: int
    status: str
    razorpay_order_id: str | None
    tracking_note: str | None
    created_at: datetime
