from app.services.review_submit.base import ReviewSubmitProvider, SubmitRequest, SubmitResult, SubmitUnavailable  # noqa: F401
from app.services.review_submit.google_direct import GoogleDirectProvider
from app.services.review_submit.handoff import HandoffProvider

HANDOFF = HandoffProvider()
DIRECT = GoogleDirectProvider()


def provider_for(location) -> ReviewSubmitProvider:
    """Direct submission only when a real, approved implementation says it is available for this location; otherwise the supported handoff."""
    return DIRECT if DIRECT.available(location) else HANDOFF