"""Tracked review links (Pro): "link clicked", and nothing more.

What a link is: a long random token that leads to ONE destination fixed when the link was made (the business's own review page). The redirect route accepts no destination of any kind from the request, so
it can never be used as an open redirect. A link belongs to the business and dies only with it: deleting the message or the customer it was sent to does not break it for someone who still holds it.

What a click is: someone opened the link. It can include a link preview, a security scanner or an email or chat app checking the page, so FlowQR leaves out HEAD requests and known bot and preview agents,
and counts repeat opens of one link within WHATSAPP_LINK_DEDUPE_SECONDS once. Even so it is a guide, not proof that a person read the message. It is NEVER shown as "review left" and never as a rating:
a click says nothing about whether anyone wrote a review or what they thought.

What is stored per click: the link, the customer, the message and the time. No address, no browser, no place. Counting is part of the Pro add-on and only happens when the business turned it on for the
review request; without it the link still goes to its destination.
"""
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppLink, WhatsAppLinkClick
from app.services import cards
from app.services.whatsapp import addons

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,64}")
# the card scanner's list of bots and preview fetchers, plus mail and chat security scanners and common HTTP libraries
BOT_PATTERN = re.compile(cards.BOT_PATTERN.pattern + r"|twitterbot|slackbot|linkedin|applebot|bingpreview|safelinks|barracuda|mimecast|proofpoint|trendmicro|virustotal|urlscan|symantec|kaspersky|"
                         r"bitdefender|sophos|netcraft|axios|node-fetch|libwww|apache-http|postman|insomnia|scrapy|http-client|aiohttp|requests", re.I)


def is_bot(user_agent: str | None) -> bool:
    """No browser name at all counts as a bot too."""
    return not (user_agent or "").strip() or bool(BOT_PATTERN.search(user_agent or ""))


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 43 characters, 256 bits of randomness


def url_for(token: str) -> str:
    return f"{settings.whatsapp_link_base_url.rstrip('/')}/{token}"


def safe_destination(url: str | None) -> str | None:
    u = (url or "").strip()
    return u if re.fullmatch(r"https://[^\s]{4,480}", u) else None


def get_or_create(db: Session, tenant_id: uuid.UUID, destination: str, idem_key: str, contact_id: uuid.UUID | None) -> WhatsAppLink | None:
    """One link per send: a retry of the same send gets the same link."""
    dest = safe_destination(destination)
    if dest is None:
        return None
    existing = db.scalar(select(WhatsAppLink).where(WhatsAppLink.tenant_id == tenant_id, WhatsAppLink.idem_key == idem_key))
    if existing is not None:
        return existing
    link = WhatsAppLink(tenant_id=tenant_id, token=new_token(), destination=dest, idem_key=idem_key[:200], contact_id=contact_id)
    db.add(link)
    db.flush()
    return link


def resolve(db: Session, token: str) -> WhatsAppLink | None:
    if not TOKEN_RE.fullmatch(token or ""):
        return None
    return db.scalar(select(WhatsAppLink).where(WhatsAppLink.token == token))


def maybe_record(db: Session, link: WhatsAppLink, user_agent: str | None, now: datetime | None = None) -> str:
    """Count this open if it should be counted. Returns why not, or "counted". Never raises into the redirect."""
    now = now or utcnow()
    if not settings.whatsapp_enabled:
        return "off"
    if is_bot(user_agent):
        return "bot"
    if link.contact_id is None:  # the customer this was sent to has been deleted: nobody is left to count a click for
        return "no_customer"
    if not addons.click_tracking_allowed(db, link.tenant_id):
        return "not_pro"
    recent = db.scalar(select(WhatsAppLinkClick.id).where(WhatsAppLinkClick.link_id == link.id, WhatsAppLinkClick.clicked_at >= now - timedelta(seconds=settings.whatsapp_link_dedupe_seconds)).limit(1))
    if recent is not None:
        return "repeat"
    db.add(WhatsAppLinkClick(tenant_id=link.tenant_id, link_id=link.id, contact_id=link.contact_id, message_id=link.message_id, clicked_at=now))
    db.flush()
    return "counted"


# ---- what the owner sees
def clicked_at_for(db: Session, tenant_id: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """The first time each message's link was clicked."""
    if not message_ids:
        return {}
    rows = db.execute(select(WhatsAppLinkClick.message_id, func.min(WhatsAppLinkClick.clicked_at)).where(WhatsAppLinkClick.tenant_id == tenant_id, WhatsAppLinkClick.message_id.in_(message_ids)).group_by(WhatsAppLinkClick.message_id)).all()
    return {m: t for m, t in rows}


def summary(db: Session, tenant_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    """Link clicks in a period: how many, how many different messages, and by day. Wording on screen is always "link clicked"."""
    base = (WhatsAppLinkClick.tenant_id == tenant_id, WhatsAppLinkClick.clicked_at >= start, WhatsAppLinkClick.clicked_at < end)
    total = db.scalar(select(func.count()).select_from(WhatsAppLinkClick).where(*base)) or 0
    messages = db.scalar(select(func.count(func.distinct(WhatsAppLinkClick.message_id))).where(*base)) or 0
    day = func.date(func.timezone("Asia/Kolkata", WhatsAppLinkClick.clicked_at))
    by_day = [{"date": d.isoformat(), "clicks": n} for d, n in db.execute(select(day, func.count()).where(*base).group_by(day).order_by(day)).all()]
    return {"enabled": addons.click_tracking_allowed(db, tenant_id), "link_clicked": total, "messages_with_a_click": messages, "by_day": by_day,
            "note": "A click means someone opened the link. It can include link previews and security scanners, so treat it as a guide. It does not mean a review was left."}
