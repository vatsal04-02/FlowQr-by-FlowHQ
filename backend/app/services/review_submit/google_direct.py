from app.core.config import settings
from app.services.review_submit.base import SubmitRequest, SubmitResult, SubmitUnavailable


class GoogleDirectProvider:
    """Placeholder for direct submission, to be implemented ONLY after Google grants FlowHQ an official, documented route.

    Why this does nothing today: Google's public Business Profile API has no create-review method, and the program Birdeye describes ("a private
    Google API" via a partnership) is not documented or open to applications. We do not use undocumented endpoints, browser automation or
    simulated submissions. So `implemented` is False, `available()` is False whatever the configuration says, and `submit()` raises. After approval:
    implement `_submit_to_google` against the documented API, set `implemented = True`, set GOOGLE_DIRECT_SUBMISSION=approved, and verify with a real
    published test review before announcing the feature (docs/GOOGLE_DIRECT_REVIEWS.md).
    """

    name = "google_direct"
    mode = "direct"
    implemented = False  # flipped to True only together with a real, approved, verified implementation

    def available(self, location) -> bool:
        return bool(self.implemented and settings.google_direct_submission == "approved")  # a flag alone can never switch this on

    def capabilities(self) -> dict:
        return {"requires_customer_google_sign_in": True, "submits_for_customer": True}  # expected for any partner route; confirm from Google's terms

    def submit(self, request: SubmitRequest) -> SubmitResult:
        if not self.implemented:
            raise SubmitUnavailable("Direct submission is not available: it requires Google's approval and API access", code="not_authorized")
        return self._submit_to_google(request)

    def _submit_to_google(self, request: SubmitRequest) -> SubmitResult:  # pragma: no cover - intentionally unimplemented
        raise NotImplementedError("Implement against Google's documented API after partnership approval")