from app.services.review_submit.base import SubmitRequest, SubmitResult, SubmitUnavailable


class HandoffProvider:
    """The supported route: copy to clipboard, open Google's Write-a-review page, the customer pastes and posts. Nothing is submitted by FlowQR."""

    name = "handoff"
    mode = "handoff"

    def available(self, location) -> bool:
        return True

    def capabilities(self) -> dict:
        return {"requires_customer_google_sign_in": False, "submits_for_customer": False}

    def submit(self, request: SubmitRequest) -> SubmitResult:
        raise SubmitUnavailable("FlowQR does not submit reviews to Google; the customer posts it themselves", code="handoff_only")