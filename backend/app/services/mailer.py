"""Outbound email. SMTP when configured; otherwise a clearly-labelled dev log (never in production)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("flowqr.mailer")
OUTBOX: list[dict] = []  # populated only when APP_ENV=test (assertable in tests)


def send_email(to: str, subject: str, body: str) -> bool:
    """Returns True if the message was handed to an SMTP server."""
    if settings.app_env == "test":
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        return True
    if settings.smtp_host:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
            return True
        except (smtplib.SMTPException, OSError) as exc:
            log.error("SMTP delivery to %s failed: %s", to, type(exc).__name__)  # no body/links in logs
            return False
    if settings.hardened:
        log.warning("Email not sent to %s (%s): SMTP is not configured (SMTP_HOST)", to, subject)
        return False
    log.info("[DEV EMAIL - not delivered] to=%s subject=%s\n%s", to, subject, body)
    return False
