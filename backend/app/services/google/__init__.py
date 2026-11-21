from app.services.google.errors import (  # noqa: F401
    GoogleAgencyUnavailable, GoogleAPIError, GoogleApiNotApproved, GoogleAuthRevoked, GoogleError, GoogleNotConfigured, GoogleRateLimited, GoogleScopeMissing,
)
from app.services.google.provider import GoogleBusinessProvider, HttpGoogleProvider


def get_google_provider() -> GoogleBusinessProvider:
    """Factory; tests replace this with a clearly-labelled fake."""
    return HttpGoogleProvider()
