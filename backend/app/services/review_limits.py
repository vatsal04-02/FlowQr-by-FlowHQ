"""How many AI-written versions one customer visit may get, per business. The default is REVIEW_MAX_AI_WRITES_PER_SESSION (2). For TESTING a named business can be given more with
REVIEW_AI_WRITES_OVERRIDES="<business id>:10,<business id>:5" (empty = nobody; entries that are not a real id and a whole number are ignored; no business can be given more than MAX_OVERRIDE).
This only raises the per-visit count. The monthly plan allowance, the platform AI spending cap and every safety check apply to that business exactly as before."""
import uuid

from app.core.config import settings

MAX_OVERRIDE = 20


def _overrides() -> dict[uuid.UUID, int]:
    out: dict[uuid.UUID, int] = {}
    for part in (settings.review_ai_writes_overrides or "").split(","):
        key, _, num = part.strip().partition(":")
        try:
            n = int(num)
            if 1 <= n <= MAX_OVERRIDE:
                out[uuid.UUID(key.strip())] = n
        except ValueError:
            continue
    return out


def _tenant(tenant_id: uuid.UUID | str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(tenant_id)) if tenant_id else None
    except ValueError:
        return None


def ai_write_limit(tenant_id: uuid.UUID | str | None) -> int:
    """AI-written versions one customer visit may get for this business."""
    t = _tenant(tenant_id)
    return _overrides().get(t, settings.review_max_ai_writes_per_session) if t else settings.review_max_ai_writes_per_session


def draft_limit(tenant_id: uuid.UUID | str | None) -> int:
    """Drafts one visit may hold: the normal limit, or at least the business's test allowance when it has one."""
    t = _tenant(tenant_id)
    n = _overrides().get(t) if t else None
    return max(settings.review_max_drafts_per_session, n) if n else settings.review_max_drafts_per_session
