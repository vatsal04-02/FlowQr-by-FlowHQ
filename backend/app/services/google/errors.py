class GoogleError(Exception):
    pass


class GoogleNotConfigured(GoogleError):
    """GOOGLE_CLIENT_ID/SECRET are missing: integration is in the configuration-pending state."""


class GoogleAuthRevoked(GoogleError):
    """The user revoked access or the refresh token is no longer valid."""


class GoogleScopeMissing(GoogleAuthRevoked):
    """Google accepted the sign-in but the `business.manage` scope was not granted (the user unticked it on the consent
    screen, or the token was issued without it). The only fix is to reconnect and grant it, so it is handled like a revocation."""


class GoogleAgencyUnavailable(GoogleAuthRevoked):
    """The agency account cannot act: agency management is switched off, the agency login was revoked, or the key is missing. Handled like a revoked connection by every caller
    (nothing is sent to Google), but it does NOT change the connection's stored state: switching the flag back on resumes it."""


class GoogleRateLimited(GoogleError):
    def __init__(self, retry_after: int | None = None, quota_metric: str | None = None):
        super().__init__("Google API quota/rate limit reached")
        self.retry_after = retry_after
        self.quota_metric = quota_metric  # ErrorInfo.metadata.quota_metric when Google sent it


class GoogleAPIError(GoogleError):
    def __init__(self, status: int, message: str = "", *, reason: str | None = None, google_status: str | None = None):
        super().__init__(f"Google API error {status}: {message}"[:300])
        self.status = status
        self.reason = reason  # google.rpc.ErrorInfo.reason, e.g. IAM_PERMISSION_DENIED
        self.google_status = google_status  # google.rpc.Code name, e.g. PERMISSION_DENIED

    @property
    def transient(self) -> bool:
        return self.status >= 500


class GoogleApiNotApproved(GoogleAPIError):
    """The OAuth login worked but the FlowHQ Cloud project cannot call the Business Profile APIs yet. Not retryable until fixed.

    `why`:
      * "quota_zero"       - Google's documented signal for "access request not approved yet" (quota 0 QPM).
      * "service_disabled" - ErrorInfo reason SERVICE_DISABLED: the API named in `service` is not enabled on the project.
    """

    def __init__(self, status: int, message: str = "", *, why: str = "quota_zero", service: str | None = None):
        super().__init__(status, message, reason="SERVICE_DISABLED" if why == "service_disabled" else "RATE_LIMIT_EXCEEDED")
        self.why = why
        self.service = service
        self.args = ("Google Business Profile API access is awaiting approval for this project" if why == "quota_zero"
                     else f"A Google Business Profile API is not enabled on the project ({service or 'unknown service'})",)

    @property
    def transient(self) -> bool:
        return False
