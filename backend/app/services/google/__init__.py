from app.services.google.errors import (  # noqa: F401
    GoogleAPIError, GoogleAuthRevoked, GoogleError, GoogleNotConfigured, GoogleRateLimited,
)
from app.services.google.provider import GoogleBusinessProvider, HttpGoogleProvider


def get_google_provider() -> GoogleBusinessProvider:
    """Factory; tests replace this with a clearly-labelled fake."""
    return HttpGoogleProvider()
