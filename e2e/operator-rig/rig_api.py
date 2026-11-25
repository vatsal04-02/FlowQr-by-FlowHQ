"""UI RIG ONLY (never shipped, never run against Google or a real AI): the real FlowQR API from this branch on a throwaway database, with Google replaced by the in-memory V2 test double and the AI
replaced by a scripted stand-in, plus /rig/* controls so a browser test can put both into the state it wants to look at. Everything the browser sees comes from the real routes, the real policy
engine, the real executor and the real database. It proves what the screens do with what the server tells them. It proves NOTHING about Google or about how a real model behaves."""
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("APP_ENV", "test")
os.environ["TOKEN_ENCRYPTION_KEY"] = "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU="
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ.update({"GOOGLE_CLIENT_ID": "rig-client", "GOOGLE_CLIENT_SECRET": "rig-secret", "GOOGLE_REDIRECT_URI": "http://localhost:3000/api/v1/google/callback", "FRONTEND_URL": "http://localhost:3000",
                   "PUBLIC_CARD_BASE_URL": "http://localhost:3000", "RATE_LIMIT_ENABLED": "false", "AI_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "rig-key", "OPENROUTER_MODEL": "rig/model"})

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import system_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services import google as g  # noqa: E402
from app.services.ai.base import AIUnavailable  # noqa: E402
from tests.test_seo_v2_engine import V2Google  # noqa: E402

G = V2Google()
g.get_google_provider = lambda: G


class RigAI:
    """The scripted stand-in for the AI: the browser test queues what it should answer (`/rig/ai`). The queue's last item repeats. `down` makes every call fail like an empty or bad key."""
    name, model, usage = "rig-ai", "rig-model", None

    def __init__(self):
        self.outputs, self.prompts, self.down = ["Thank you for visiting. We are glad you shared your feedback."], [], None

    def generate(self, system, user, **kw):
        self.prompts.append(user)
        if self.down:
            raise AIUnavailable("rig: the AI is down", code=self.down)
        return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]


AI = RigAI()
import app.services.ai as ai_pkg  # noqa: E402

for target in ("app.api.v1.operator", "app.api.v1.agent", "app.api.v1.posts", "app.api.v1.reviews", "app.services.agent.plan", "app.services.ai"):
    __import__(target)
    setattr(sys.modules[target], "get_provider", lambda: AI)

rig = APIRouter(prefix="/rig")


class Ai(BaseModel):
    outputs: list[str] | None = None
    down: str | None = None
    reset: bool = False


@rig.post("/ai")
def set_ai(b: Ai):
    if b.outputs is not None:
        AI.outputs = list(b.outputs)
    AI.down = b.down or None
    if b.reset:
        AI.prompts.clear()
    return {"ok": True, "prompts": len(AI.prompts)}


@rig.get("/ai")
def get_ai():
    return {"prompts": AI.prompts, "down": AI.down}


class Details(BaseModel):
    key: str
    value: object = None


@rig.post("/google/details")
def set_details(b: Details):
    G.details[b.key] = b.value
    return {"ok": True}


@rig.get("/google")
def get_google():
    return {"details": G.details, "update_calls": G.update_calls, "writes": [(k, list(v) if isinstance(v, dict) else v) for k, v in G.writes], "posts": len(G.posts)}


class Setting(BaseModel):
    attr: str
    value: object = None


@rig.post("/setting")
def set_setting(b: Setting):
    setattr(settings, b.attr, b.value)
    return {"ok": True}


@rig.post("/sql")
def sql(b: dict):
    s = system_session()
    try:
        s.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        r = s.execute(text(b["q"]), b.get("p", {}))
        rows = [list(x) for x in r.fetchall()] if r.returns_rows else []
        s.commit()
    finally:
        s.close()
    return {"ok": True, "rows": rows}


app.include_router(rig)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
