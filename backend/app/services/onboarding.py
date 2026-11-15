"""The "getting started" checklist: what a business owner has done and what to do next, computed ONLY from what is in the database.

Nothing here is a placeholder or a demo: a step is done when the real record exists (a location, a connected Google account with a chosen location, a campaign, an assigned card,
a plan or an active free period, a saved notification choice). Steps the plan does not include are shown as locked with the plan that adds them, never hidden and never faked.
Progress survives leaving the page because it is derived from the data, not from a saved flag."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentSettings, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Location, NotificationPref, QRCard, Review, ReviewCampaign, Subscription, Tenant, User,
)
from app.models.cards import CardStatus
from app.services import entitlements as ent

CARD_STATES = (CardStatus.assigned, CardStatus.active, CardStatus.paused, CardStatus.reserved)


def steps(db: Session, tenant_id: uuid.UUID, user: User) -> dict:
    t = db.get(Tenant, tenant_id)
    e = ent.for_tenant(db, tenant_id)
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    count = lambda q: db.scalar(q) or 0  # noqa: E731
    locations = count(select(func.count()).select_from(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True)))
    with_link = count(select(func.count()).select_from(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True), Location.review_url.is_not(None), Location.review_url != ""))
    conn = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant_id, GoogleConnection.status == GoogleConnectionStatus.active).limit(1))
    chosen = count(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.tenant_id == tenant_id, GoogleLocation.selected.is_(True)))
    campaigns = count(select(func.count()).select_from(ReviewCampaign).where(ReviewCampaign.tenant_id == tenant_id, ReviewCampaign.status == "active"))
    cards = count(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == tenant_id, QRCard.status.in_(CARD_STATES)))
    reviews = count(select(func.count()).select_from(Review).where(Review.tenant_id == tenant_id))
    prefs = count(select(func.count()).select_from(NotificationPref).where(NotificationPref.tenant_id == tenant_id, NotificationPref.user_id == user.id))
    settings_row = db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tenant_id))
    paid = bool(sub and sub.status == "active" and sub.source == "razorpay")

    if paid:
        plan_state = ("done", f"You are on the {sub.plan.title()} plan.")
    elif e.promo:
        plan_state = ("free", f"Your free {e.promo['plan_name']} month runs to {e.promo['ends_at']:%d %b %Y}. Nothing is charged when it ends; choose a plan when you are ready.")
    elif sub and sub.status == "trialing" and e.active:
        plan_state = ("free", f"Your free trial has {e.trial_days_left} days left. You choose whether to continue; nothing is charged automatically.")
    else:
        plan_state = ("todo", "Choose a plan to keep using FlowQR.")

    def step(id_, title, why, done, href, cta, *, optional=False, note=None, locked=None):
        return {"id": id_, "title": title, "why": why, "done": bool(done), "optional": optional, "href": href, "cta": cta, "note": note, "locked": locked}

    out = [
        step("verify_email", "Confirm your email address", "So invitations, receipts and alerts reach you.", bool(user.email_verified_at), "/settings/account", "Open account settings"),
        step("location", "Add your location", "Each branch gets its own cards and its own reviews.", locations >= 1, "/overview/locations", "Add a location"),
        step("review_link", "Set your Google review link", "Where customers are sent to leave their review. Cards keep working when you change it.", with_link >= 1, "/overview/locations", "Add the link"),
        step("google", "Connect your Google Business Profile", "Lets FlowQR read your reviews and, only when you approve, publish replies and updates. It is optional: your cards work without it. You can disconnect at any time.",
             bool(conn and chosen), "/gbp/locations", "Connect Google", optional=True,
             note=("Don't have a Business Profile yet? You can create one for free at business.google.com, then come back; until then everything that does not need Google still works." if not conn else None)),
        step("campaign", "Create your first review campaign", "A campaign is the page customers see when they scan your card.", campaigns >= 1, "/gbp/campaigns", "Create a campaign"),
        step("card", "Assign a physical card", "Put the card where customers will see it. The same card keeps working if you change the campaign later.", cards >= 1, "/gbp/cards", "Assign a card", optional=True,
             note=("No cards yet? You can order them from Settings > Plan & billing > Payments." if cards == 0 else None)),
        step("plan", "Choose a plan, or use your free period", plan_state[1], plan_state[0] in ("done", "free"), "/settings/billing", "See plans"),
        step("notifications", "Choose how we tell you about reviews", "Email alerts for new and flagged reviews. The defaults are on only for flagged reviews.", prefs >= 1, "/settings/notifications", "Choose", optional=True),
        step("first_review", "See your first review here", "Reviews appear after Google is connected and synced, or after a customer's review is recorded.", reviews >= 1, "/gbp/reviews", "Open reviews", optional=True),
    ]
    out.append(step("autonomy", "Decide what FlowQR may do on its own", "Everything starts switched off. You choose, per kind of change; posts, photos and replies always need you.",
                    bool(settings_row and (settings_row.autonomy_enabled or settings_row.autonomy_permissions_at)), "/ai/autonomy", "Review autonomy settings", optional=True,
                    locked=None if "autonomy" in e.features else "Included in Growth and Pro"))
    required = [s for s in out if not s["optional"] and not s["locked"]]
    done_required = [s for s in required if s["done"]]
    nxt = next((s for s in out if not s["done"] and not s["locked"] and not s["optional"]), None) or next((s for s in out if not s["done"] and not s["locked"]), None)
    return {"steps": out, "required_total": len(required), "required_done": len(done_required), "complete": len(done_required) == len(required), "next": nxt["id"] if nxt else None,
            "business": t.name if t else None}
