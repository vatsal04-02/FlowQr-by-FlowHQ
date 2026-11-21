"""Every change of an agency authorization's status is written to the audit log, whichever code path made it.

The flow changes `status` in many places (steps, failures, waits, stop, loss, switch). Auditing each by hand is how a transition gets missed, so it is done once, here, where it cannot be skipped:
a session-wide listener sees every authorization whose status is about to change in a flush and adds one `google.agency.transition` entry in the SAME transaction (so a rolled-back change leaves no
entry, and a committed one always has one). The entry says what changed and which failure code was recorded, and never a token, an e-mail address, a Google resource name or any Google content.
"""
import uuid

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import AuditLog, GoogleAgencyAuthorization
from app.models.base import utcnow


@event.listens_for(Session, "before_flush")
def _audit_status_transitions(session: Session, flush_context, instances) -> None:
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, GoogleAgencyAuthorization):
            continue
        history = inspect(obj).attrs.status.history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else obj.status
        if old == new:
            continue
        if obj.id is None:  # a new row gets its id at flush; the audit entry needs it now
            obj.id = uuid.uuid4()
        session.add(AuditLog(tenant_id=obj.tenant_id, user_id=None, action="google.agency.transition", entity_type="google_agency_authorization", entity_id=str(obj.id),
                             meta={"from": old, "to": new, "code": obj.failure_code, "target": obj.target_type, "scope": obj.invite_scope}, ip=None, created_at=utcnow()))
