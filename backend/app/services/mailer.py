"""Outbound email abstraction.

No SMTP is wired by default. In development the message is logged (clearly labelled) so the
reset/invite flows are testable. In production without SMTP configured we log a warning and
send nothing — secrets/links are never written to production logs.
"""
import logging

from app.core.config import settings

log = logging.getLogger("flowqr.mailer")


def send_email(to: str, subject: str, body: str) -> None:
    if settings.is_production:
        log.warning("Email not sent to %s (%s): SMTP provider not configured yet", to, subject)
        return
    log.info("[DEV EMAIL - not delivered] to=%s subject=%s\n%s", to, subject, body)
