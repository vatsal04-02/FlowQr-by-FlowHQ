"""A separate notice for a customer-visible change FlowQR made to a Google profile.

Google's policy asks a tool that changes an end-client's account to tell the end-client separately from Google's own notices. This is that notice for V2 profile changes: sent from FlowQR (not Google)
to the person who approved the change, only AFTER Google's profile was read back and shows it. It says what changed, where the full record is, how to undo it (FlowQR never reverts a change by itself:
it would be an edit the owner has not asked for) and how to stop FlowQR. A mail problem never affects the change: the history is the record, the notice is a courtesy that is also audited."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentAction, AgentActionApproval, GoogleLocation, User
from app.services.agent import autonomy_policy as pol
from app.services.agent.v2 import present
from app.services.audit import audit

log = logging.getLogger("flowqr.v2notice")


def notice_text(a: AgentAction, where: str, label: str) -> tuple[str, str]:
    d = present.describe(a.field_key, a.current_value.get("value"), a.proposed_value.get("canonical"), a.evidence)
    lines = [f"  + {x}" for x in d["added"][:8]] + [f"  - {x}" for x in d["removed"][:8]]
    more = max(0, len(d["added"]) - 8) + max(0, len(d["removed"]) - 8)
    subject = f"FlowQR changed {label.lower()} on your Google profile for {where}"
    body = (f"Hi,\n\nThis is a separate notice from FlowQR, not from Google.\n\n"
            f"You approved a change to {label.lower()} on your Google Business Profile for {where}. FlowQR made it and then read your profile back from Google, which now shows it.\n\n"
            + ("What changed:\n" + "\n".join(lines) + (f"\n  ...and {more} more" if more else "") + "\n\n" if lines else "")
            + f"The full record, with the before and after, is in your Activity history: {settings.frontend_url}/ai/activity\n\n"
            "FlowQR never undoes a change on its own. To change it back, edit it in Google Business Profile.\n\n"
            f"To stop FlowQR making changes to this profile, open {settings.frontend_url}/gbp/locations and disconnect Google. FlowQR stops at once and removes its access.\n")
    return subject, body


def send_change_notice(db: Session, a: AgentAction) -> bool:
    """Send the notice for a verified V2 change to whoever approved it. Never raises. Returns True when handed to the mail server."""
    if a.field_key not in pol.V2_FIELDS or a.subject_type is not None:
        return False
    try:
        ap = db.scalar(select(AgentActionApproval).where(AgentActionApproval.action_id == a.id, AgentActionApproval.decision == "approved", AgentActionApproval.authorized_by.is_not(None))
                       .order_by(AgentActionApproval.decided_at.desc()).limit(1))
        user = db.get(User, ap.authorized_by) if ap is not None else None
        if user is None or not user.email:
            return False
        gl = db.get(GoogleLocation, a.google_location_id)
        from app.services.mailer import send_email

        subject, body = notice_text(a, (gl.title if gl else None) or "your business", pol.SPECS[a.action_type].label)
        ok = send_email(user.email, subject, body)
    except Exception as exc:  # noqa: BLE001 - a mail problem must never undo or hide a verified change
        log.warning("change notice failed: %s", type(exc).__name__)
        ok = False
    audit(db, action="email.sent" if ok else "email.failed", tenant_id=a.tenant_id, entity_type="agent_action", entity_id=a.id, meta={"kind": "seo_v2_change_notice", "field": a.field_key})
    return ok
