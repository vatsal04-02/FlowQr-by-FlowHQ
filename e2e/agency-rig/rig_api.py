"""UI RIG ONLY (never shipped, never run against Google): the real FlowQR API from this branch on a throwaway database, with Google replaced by the in-memory fake, plus /rig/* controls so a
browser test can put the fake into the state it wants to look at (pending, blocked, failed ...). Everything the browser sees comes from the real routes and the real database."""
import os
import sys

sys.path.insert(0, "/app")
from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("APP_ENV", "test")
os.environ["TOKEN_ENCRYPTION_KEY"] = "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU="
os.environ["AGENCY_TOKEN_ENCRYPTION_KEY"] = os.environ.get("AGENCY_TOKEN_ENCRYPTION_KEY") or Fernet.generate_key().decode()
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ.update({"GOOGLE_CLIENT_ID": "rig-client", "GOOGLE_CLIENT_SECRET": "rig-secret", "GOOGLE_REDIRECT_URI": "http://localhost:3000/api/v1/google/callback",
                   "GOOGLE_AGENCY_MANAGER_ENABLED": "true", "GOOGLE_AGENCY_SELF_SERVICE_ENABLED": "true", "GOOGLE_AGENCY_LOCATION_GROUP_ID": "5488245563",
                   "GOOGLE_AGENCY_OPERATOR_EMAILS": "ui-operator@flowhq.example", "PLATFORM_ADMIN_EMAILS": "ui-operator@flowhq.example,ops@flowhq.example",
                   "FRONTEND_URL": "http://localhost:3000", "PUBLIC_CARD_BASE_URL": "http://localhost:3000", "RATE_LIMIT_ENABLED": "false"})

from fastapi import APIRouter  # noqa: E402
from sqlalchemy import text  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import system_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services import google as g  # noqa: E402
from app.services.google import agency, agency_client as ac  # noqa: E402
from app.services.google.errors import GoogleAPIError  # noqa: E402
from app.services.google.provider import GAccount, GLocation, TokenSet  # noqa: E402
from tests.fake_agency_google import CLIENT_ACCESS, CLIENT_REFRESH, FakeAgencyClient  # noqa: E402

AGENCY_EMAIL = "flowqr-agency@flowhq.example"
f = FakeAgencyClient(AGENCY_EMAIL)
real_accounts, real_locations = f.list_accounts, f.list_locations
f.exchange_code_agency = f.exchange_code
f.exchange_code = lambda code: TokenSet(CLIENT_ACCESS, 3600, CLIENT_REFRESH, "openid email https://www.googleapis.com/auth/business.manage")
f.get_userinfo = lambda at: {"sub": "rig-customer-sub", "email": "owner@rig-clinic.example"} if at == CLIENT_ACCESS else {"sub": "agency-sub-1", "email": AGENCY_EMAIL}
f.list_accounts = lambda token: [GAccount("accounts/111", "Rig Clinic")] if token == CLIENT_ACCESS else real_accounts(token)
f.list_locations = lambda token, acct: ([GLocation(acct, "locations/222", "Rig Clinic Gomti Nagar", "Gomti Nagar, Lucknow", "PID1", "https://g.page/r/RIG/review"),
                                         GLocation(acct, "locations/333", "Rig Clinic Aliganj", "Aliganj, Lucknow", "PID2", None)] if token == CLIENT_ACCESS else real_locations(token, acct))
g.get_google_provider = lambda: f
ac.get_agency_client = lambda: f

# the agency login: registered once, as the real CLI does it (here with the fake's code exchange)
f.exchange_code = f.exchange_code_agency
try:
    agency.register_account("rig-agency", code="rig", provider=f)
except Exception as exc:  # noqa: BLE001
    print("agency register:", type(exc).__name__, exc)
f.exchange_code = lambda code: TokenSet(CLIENT_ACCESS, 3600, CLIENT_REFRESH, "openid email https://www.googleapis.com/auth/business.manage")

rig = APIRouter(prefix="/rig")


class Set(BaseModel):
    attr: str
    value: object = None
    error_status: int | None = None


@rig.post("/fake")
def set_fake(b: Set):
    value = GoogleAPIError(b.error_status, "rig") if b.error_status else b.value
    setattr(f, b.attr, value)
    return {"ok": True}


@rig.post("/setting")
def set_setting(b: Set):
    setattr(settings, b.attr, b.value)
    return {"ok": True}


@rig.post("/reset")
def reset():
    f.accept_error = f.invite_error = f.remove_error = f.list_error = None
    f.visible_after_accept, f.agency_in_group = True, True
    f.admins.clear(); f.invitations.clear(); f.group_invitations.clear(); f.group_sees.clear(); f.agency_sees.clear(); f.calls.clear()
    return {"ok": True}


@rig.post("/client-removes")
def client_removes():
    f.client_removes_agency("locations/222")
    return {"ok": True}


@rig.post("/sql")
def sql(b: dict):
    s = system_session()
    try:
        s.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        s.execute(text(b["q"]), b.get("p", {}))
        s.commit()
    finally:
        s.close()
    return {"ok": True}


@rig.get("/outbox")
def outbox(to: str):
    from app.services.mailer import OUTBOX

    return [{"subject": m["subject"], "body": m["body"]} for m in OUTBOX if m["to"] == to]


app.include_router(rig)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
