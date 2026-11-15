"""FlowHQ operations: platform health for admins, and the signed-in browser's crash reports (relayed to error monitoring)."""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core import monitoring
from app.core.deps import AuthContext, get_auth_context, require_platform_admin
from app.core.rate_limit import hit
from app.services import ops

log = logging.getLogger("flowqr.client")
router = APIRouter(tags=["ops"])


@router.get("/admin/ops")
def platform_health(ctx: AuthContext = Depends(require_platform_admin)):
    """Every check the platform runs on itself: database, Redis, migrations, worker and scheduler, failed jobs, Google, AI budget, billing, backups, monitoring."""
    return ops.run_checks(ctx.db)


@router.get("/admin/ai-quality")
def platform_ai_quality(days: int = Query(90, ge=7, le=365), ctx: AuthContext = Depends(require_platform_admin)):
    """AI Output Acceptance Rate across all businesses (counts and rates only, never text)."""
    from app.services.ai import outcomes
    return {"days": days, "accept_rule": f"Approved with at most {int(outcomes.ACCEPT_EDIT_RATIO * 100)}% of the words changed", "kinds": outcomes.summary(ctx.db, None, days)}


class ClientError(BaseModel):
    message: str = Field(max_length=300)
    digest: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=200)


@router.post("/monitoring/client-error", status_code=204)
def client_error(body: ClientError, ctx: AuthContext = Depends(get_auth_context)):
    """A signed-in browser reports that a page crashed. Only the error text, Next.js digest and path are kept (no user, no page content)."""
    if not hit(f"clienterr:{ctx.user.id}", 10, 600):
        return
    log.error("browser page error path=%s digest=%s message=%s", body.path, body.digest, body.message[:200])
    monitoring.capture_message("browser page error: " + body.message, "error", where="browser", path=(body.path or "")[:60])
