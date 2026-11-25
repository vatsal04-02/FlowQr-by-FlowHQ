"""UI RIG ONLY (never shipped, never run against Google or a real AI): the real FlowQR API on a throwaway database with the AI website builder switched on, the AI replaced by a scripted stand-in,
and the worker replaced by a thread that pauses a moment after each real step so a browser can watch it. It proves what the screens do with what the server tells them, nothing about a real model."""
import json
import os
import sys
import threading
import time

sys.path.insert(0, "/app")
os.environ.setdefault("APP_ENV", "test")
os.environ["TOKEN_ENCRYPTION_KEY"] = "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU="
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ.update({"SITES_AI_BUILDER_ENABLED": "true", "RATE_LIMIT_ENABLED": "false", "FRONTEND_URL": "http://localhost:3012", "PUBLIC_CARD_BASE_URL": "http://localhost:3012",
                   "AI_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "rig-key", "OPENROUTER_MODEL": "rig/model"})

from fastapi import APIRouter  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import system_session  # noqa: E402
from app.main import app  # noqa: E402
from app.api.v1 import website as website_api  # noqa: E402
from app.services.sites import generator as gen  # noqa: E402

PLAN = json.dumps({"template": "clinic", "accent": "teal", "audience": "People in Lucknow with back or neck pain."})
COPY = json.dumps({"eyebrow": "Appointments", "headline": "Physiotherapy for back and neck pain in Lucknow", "subheading": "Calm, clear care close to home.", "about_heading": "About the clinic",
                   "about": "We help people with back and neck pain understand what is going on and move comfortably again.", "services_heading": "What we help with", "services_intro": "Tell us what hurts.",
                   "services": [{"title": "Back care", "description": "Assessment and a plan for an aching back."}, {"title": "Neck pain physiotherapy", "description": "Help with a stiff or painful neck."}],
                   "contact_heading": "Book a visit", "contact_intro": "Send a message and we will call you back.", "seo_title": "Physiotherapy in Lucknow", "seo_description": "Back and neck pain physiotherapy in Lucknow."})
STATE = {"edit": None, "delay": 0.7}


class RigAI:
    name, model, usage = "rig-ai", "rig-model", None

    def generate(self, system, user, **kw):
        if "edit a small business website" in system:
            req = json.loads(user)
            hero = next(s for s in req["sections"] if s["type"] == "hero")
            return json.dumps({"changes": [{"op": "set_text", "section_id": hero["id"], "field": "heading", "value": "Move comfortably again"}], "cannot": ""})
        return PLAN if "TEMPLATES:" in user else COPY


gen.get_provider = lambda: RigAI()
website_api.get_provider = lambda: RigAI()
_real_set = gen._set


def slow_set(db, job, key, status, note=None):
    _real_set(db, job, key, status, note)
    time.sleep(STATE["delay"] / (1 if status == "running" else 3))


gen._set = slow_set


def run_in_thread(job_id):
    def go():
        db = system_session()
        try:
            gen.run(db, job_id)
        finally:
            db.close()

    threading.Thread(target=go, daemon=True).start()


gen.enqueue = run_in_thread

rig = APIRouter(prefix="/rig")


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
