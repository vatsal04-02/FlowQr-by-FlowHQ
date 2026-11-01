class GoogleError(Exception):
    pass


class GoogleNotConfigured(GoogleError):
    """GOOGLE_CLIENT_ID/SECRET are missing: integration is in the configuration-pending state."""


class GoogleAuthRevoked(GoogleError):
    """The user revoked access or the refresh token is no longer valid."""


class GoogleRateLimited(GoogleError):
    def __init__(self, retry_after: int | None = None):
        super().__init__("Google API quota/rate limit reached")
        self.retry_after = retry_after


class GoogleAPIError(GoogleError):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"Google API error {status}: {message}"[:300])
        self.status = status

    @property
    def transient(self) -> bool:
        return self.status >= 500
