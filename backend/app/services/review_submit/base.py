"""How a customer's approved review reaches Google: a provider seam.

Two kinds of provider exist:

* ``handoff`` (the only one that is real today): FlowQR copies the review to the customer's clipboard and opens Google's own Write-a-review
  page. The customer pastes and posts it themselves. This is the best SUPPORTED route: Google's public Business Profile API has no method to
  create a review (its Reviews resource offers get, list, updateReply and deleteReply only).
* ``direct``: the review is submitted to Google from inside FlowQR without opening Google's page. That needs a Google-side program or API
  that is NOT publicly documented or open to apply for (Birdeye describes a "private Google API" under a partnership). See
  docs/GOOGLE_DIRECT_REVIEWS.md. No such API is called anywhere in this codebase, nothing is simulated, and the direct provider reports itself
  unavailable until a real, approved implementation is registered.

Rules every provider must keep (the page and the endpoint enforce them, a provider cannot opt out):
  equal access (the rating never changes whether, where or how a customer can submit), customer consent (explicit, recorded, for the exact text),
  authenticity (the customer's own final wording, never altered by a provider) and honesty (success is reported only when Google confirmed it).
"""
from dataclasses import dataclass
from typing import Literal, Protocol


class SubmitUnavailable(Exception):
    """This provider cannot submit right now. `code` is a stable reason for logs (never shown raw to customers)."""

    def __init__(self, message: str = "", *, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SubmitRequest:
    tenant_id: object
    location_id: object
    rating: int
    text: str
    language: str


@dataclass(frozen=True)
class SubmitResult:
    """`published` only when Google itself confirmed the review (then `external_ref` is its id). Anything else is NOT a published review."""

    status: Literal["published", "pending", "rejected", "failed"]
    external_ref: str | None = None
    message: str | None = None


class ReviewSubmitProvider(Protocol):
    name: str
    mode: Literal["handoff", "direct"]

    def available(self, location) -> bool: ...

    def capabilities(self) -> dict: ...

    def submit(self, request: SubmitRequest) -> SubmitResult: ...