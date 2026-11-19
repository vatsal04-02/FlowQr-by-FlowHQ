"""Message templates. The business never writes a template: FlowQR submits a small set of fixed, neutral ones to Meta on the business's own account, then tracks what Meta decided.

Rules enforced here and in the sender:
* only an `approved` template can ever be sent, and only through the business's own connection;
* what a template IS (marketing or utility) is what Meta says it is, not what FlowQR asked for. Meta may re-categorise at approval. The consent needed is decided by the template's ACTUAL category,
  so a review request that Meta classifies as marketing is sent only to people who agreed to offers;
* wording is fixed and neutral. The review request never steers or filters: it goes to every customer who agreed to visit updates and asks for honest feedback;
* Meta's rules are kept: a variable never starts or ends the body, and variables hold short single-line text.
"""
import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.whatsapp import WhatsAppConnection, WhatsAppTemplate
from app.services.audit import audit
from app.services.whatsapp import WaError
from app.services.whatsapp.meta import MetaError, get_meta_client

LANGUAGE = "en"
STANDARD = {
    "review_followup": {
        "category": "utility", "variables": ["customer_name", "business_name", "review_link"],
        "body": "Hi {{1}}, thank you for visiting {{2}}. If you have a minute, we would value your honest feedback: {{3}}. Thank you.",
        "examples": ["Asha", "Asha Physio Clinic", "https://g.page/r/example/review"],
    },
    "enquiry_ack": {
        "category": "utility", "variables": ["customer_name", "business_name"],
        "body": "Hi {{1}}, thank you for contacting {{2}}. We have received your enquiry and will get back to you soon.",
        "examples": ["Asha", "Asha Physio Clinic"],
    },
    "enquiry_followup": {
        "category": "utility", "variables": ["customer_name", "business_name"],
        "body": "Hi {{1}}, we are following up on your enquiry with {{2}}. If you still need help, just reply to this message.",
        "examples": ["Asha", "Asha Physio Clinic"],
    },
    "optin_confirm": {
        "category": "utility", "variables": ["customer_name", "business_name", "agreed_to"],
        "body": "Hi {{1}}, thanks for joining {{2}} on WhatsApp. You will get {{3}}. Reply STOP at any time to stop offers.",
        "examples": ["Asha", "Asha Physio Clinic", "updates about your visits and enquiries"],
    },
    "optin_confirm_offers": {
        "category": "marketing", "variables": ["customer_name", "business_name", "agreed_to"],
        "body": "Hi {{1}}, thanks for joining {{2}} on WhatsApp. You will get {{3}}. Reply STOP at any time to stop offers.",
        "examples": ["Asha", "Asha Physio Clinic", "offers and updates"],
    },
    "offer": {
        "category": "marketing", "variables": ["customer_name", "business_name", "offer_text"],
        "body": "Hi {{1}}, {{2}} has an offer for you: {{3}}. Reply STOP to stop receiving offers.",
        "examples": ["Asha", "Asha Physio Clinic", "10% off all sessions this week"],
    },
}
STATUS_MAP = {"APPROVED": "approved", "PENDING": "pending", "IN_APPEAL": "pending", "REJECTED": "rejected", "PAUSED": "paused", "DISABLED": "disabled"}
VAR = re.compile(r"\{\{(\d+)\}\}")
MAX_VAR_LEN = 200


def meta_name(key: str) -> str:
    return f"flowqr_{key}_{LANGUAGE}"


def key_of(name: str) -> str | None:
    for k in STANDARD:
        if name == meta_name(k):
            return k
    return None


def submission(key: str) -> dict:
    s = STANDARD[key]
    return {"name": meta_name(key), "language": LANGUAGE, "category": s["category"].upper(),
            "components": [{"type": "BODY", "text": s["body"], "example": {"body_text": [s["examples"]]}}]}


def valid_body(body: str) -> bool:
    """Meta refuses a body that starts or ends with a variable."""
    b = body.strip()
    return not (re.match(r"^\{\{\d+\}\}", b) or re.search(r"\{\{\d+\}\}$", b))


def clean_variable(v) -> str:
    """A template variable is short, single-line, printable text (Meta rejects newlines, tabs and long runs of spaces)."""
    t = re.sub(r"[\x00-\x1f  ​-‏‪-‮⁦-⁩]", " ", str(v if v is not None else ""))
    return re.sub(r" {2,}", " ", t).strip()[:MAX_VAR_LEN]


def first_name(full: str | None) -> str:
    n = clean_variable(full or "").split(" ")[0] if full else ""
    return n or "there"


def placeholders(body: str | None) -> int:
    return len({int(m) for m in VAR.findall(body or "")})


def _body_of(components) -> str | None:
    for c in components or []:
        if isinstance(c, dict) and str(c.get("type", "")).upper() == "BODY":
            return str(c.get("text") or "")[:1100] or None
    return None


def _category(raw) -> str:
    c = str(raw or "").lower()
    return c if c in ("marketing", "utility", "authentication") else "marketing"  # anything unknown is treated as the stricter one


def is_simple(components) -> bool:
    """True when the template is a text body (optionally a plain footer) and nothing that needs its own parameters: no header, media, buttons or carousel."""
    if not components:
        return True
    for c in components:
        t = str(c.get("type", "")).upper() if isinstance(c, dict) else ""
        if t == "BODY":
            continue
        if t == "FOOTER" and not VAR.search(str(c.get("text") or "")):
            continue
        return False
    return True


def _upsert(db: Session, conn: WhatsAppConnection, *, name: str, language: str, category: str, status: str, body: str | None, meta_id: str | None, rejection: str | None, now: datetime,
            simple: bool = True) -> WhatsAppTemplate:
    row = db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.connection_id == conn.id, WhatsAppTemplate.template_name == name, WhatsAppTemplate.language == language))
    key = key_of(name)
    schema = STANDARD[key]["variables"] if key else [f"variable_{i}" for i in range(1, placeholders(body) + 1)]
    if row is None:
        row = WhatsAppTemplate(tenant_id=conn.tenant_id, connection_id=conn.id, template_name=name, language=language, category=category, approval_status=status)
        db.add(row)
    row.category, row.approval_status, row.body_text, row.variable_schema = category, status, body, schema
    row.meta_template_id = meta_id or row.meta_template_id
    row.rejection_reason = (rejection or "")[:300] or None if status == "rejected" else None
    row.last_synced_at = now
    row.simple = simple
    return row


def _live_conn(db: Session, tenant_id: uuid.UUID) -> WhatsAppConnection:
    from app.services.whatsapp import connection
    c = connection.connected_connection(db, tenant_id)
    if c is None or c.status != "connected" or not c.waba_id:
        raise WaError(409, "not_connected", "Connect your WhatsApp number first.")
    return c


def _token(c: WhatsAppConnection) -> str:
    from app.services.whatsapp import connection
    t = connection._token_of(c)  # noqa: SLF001
    if not t:
        raise WaError(409, "not_connected", "The connection needs to be set up again. Press Connect WhatsApp.")
    return t


def install(db: Session, tenant_id: uuid.UUID, key: str, user_id: uuid.UUID | None = None, ip: str | None = None) -> WhatsAppTemplate:
    """Submit one of FlowQR's standard templates to Meta for this business's account (idempotent: an existing one is just re-read)."""
    if key not in STANDARD:
        raise WaError(404, "unknown_template", "Unknown message.")
    conn = _live_conn(db, tenant_id)
    sub = submission(key)
    assert valid_body(STANDARD[key]["body"])
    now = utcnow()
    try:
        out = get_meta_client().create_template(_token(conn), conn.waba_id, sub)
    except MetaError as exc:
        if "already" in exc.message.lower() or exc.code == 2388023:  # the template exists at Meta: read its state
            sync(db, tenant_id)
            row = db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.connection_id == conn.id, WhatsAppTemplate.template_name == sub["name"], WhatsAppTemplate.language == LANGUAGE))
            if row:
                return row
        raise WaError(502 if exc.retryable else 400, "meta_error", "WhatsApp could not accept the message just now. Please try again later.") from None
    row = _upsert(db, conn, name=sub["name"], language=LANGUAGE, category=_category(out.get("category") or sub["category"]), status=STATUS_MAP.get(str(out.get("status", "PENDING")).upper(), "pending"),
                  body=STANDARD[key]["body"], meta_id=str(out.get("id") or "") or None, rejection=None, now=now)
    db.flush()
    audit(db, action="whatsapp.template_install", tenant_id=tenant_id, user_id=user_id, entity_type="whatsapp_template", entity_id=row.id, meta={"template": sub["name"], "status": row.approval_status}, ip=ip)
    return row


def sync(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None, ip: str | None = None) -> dict:
    """Read the account's templates from Meta and update what FlowQR knows: status, the category Meta decided, rejection reasons. A template that vanished at Meta is marked disabled."""
    conn = _live_conn(db, tenant_id)
    try:
        remote = get_meta_client().list_templates(_token(conn), conn.waba_id)
    except MetaError as exc:
        raise WaError(502 if exc.retryable else 400, "meta_error", "Could not read your messages from WhatsApp just now. Please try again later.") from None
    now = utcnow()
    seen: set[tuple[str, str]] = set()
    changed = 0
    for t in remote:
        name, lang = str(t.get("name", ""))[:80], str(t.get("language", ""))[:12]
        if not name or not lang:
            continue
        seen.add((name, lang))
        before = db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.connection_id == conn.id, WhatsAppTemplate.template_name == name, WhatsAppTemplate.language == lang))
        old = (before.approval_status, before.category) if before else None
        row = _upsert(db, conn, name=name, language=lang, category=_category(t.get("category")), status=STATUS_MAP.get(str(t.get("status", "")).upper(), "disabled"), body=_body_of(t.get("components")),
                      meta_id=str(t.get("id") or "") or None, rejection=str(t.get("rejected_reason") or "") if str(t.get("rejected_reason") or "").upper() not in ("", "NONE") else None, now=now,
                      simple=is_simple(t.get("components")))
        changed += int(old != (row.approval_status, row.category))
    for row in db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.connection_id == conn.id)):
        if (row.template_name, row.language) not in seen and row.meta_template_id and row.approval_status != "disabled":
            row.approval_status, row.last_synced_at = "disabled", now
            changed += 1
    db.flush()
    if user_id:
        audit(db, action="whatsapp.template_sync", tenant_id=tenant_id, user_id=user_id, entity_type="whatsapp_connection", entity_id=conn.id, meta={"templates": len(remote), "changed": changed}, ip=ip)
    return {"templates": len(remote), "changed": changed}


def standard_row(db: Session, tenant_id: uuid.UUID, key: str) -> WhatsAppTemplate | None:
    from app.services.whatsapp import connection
    conn = connection.connected_connection(db, tenant_id)
    if conn is None:
        return None
    return db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.connection_id == conn.id, WhatsAppTemplate.template_name == meta_name(key), WhatsAppTemplate.language == LANGUAGE))


def render(template: WhatsAppTemplate, variables: list[str]) -> str:
    """The message as the customer will read it (for the preview and the owner's approval)."""
    body = template.body_text or ""
    return VAR.sub(lambda m: variables[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(variables) else m.group(0), body)


def serialize(t: WhatsAppTemplate) -> dict:
    return {"id": t.id, "name": t.template_name, "key": key_of(t.template_name), "language": t.language, "category": t.category, "status": t.approval_status, "body": t.body_text,
            "variables": t.variable_schema or [], "rejection_reason": t.rejection_reason, "synced_at": t.last_synced_at, "simple": bool(t.simple)}
