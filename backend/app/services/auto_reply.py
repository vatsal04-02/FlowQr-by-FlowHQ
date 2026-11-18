"""Template-based automatic replies to positive reviews.

OWNER DECISION, 2026-11-15 (replaces the earlier rule that every reply needed a person): a business's 4 and 5 star reviews are answered automatically from a TEMPLATE, with an off switch,
a cap that follows the plan, and every safety rule below. The earlier design is explained in docs/AI_AUTONOMY.md; what changed and why is recorded there.

What makes this safe (each rule is a test in tests/test_template_auto_replies.py):
  * NO AI WRITES THE REPLY. The text is a template the owner approved (or the built-in set) with only a first name and the business name filled in. A model cannot say something the
    business did not approve, so there is nothing to hallucinate, promise or diagnose.
  * ONLY CLEARLY POSITIVE REVIEWS: rating at or above the business's minimum (4 by default, 5 if they choose), the deterministic risk check finds no reason at all (health, legal, abuse,
    privacy, hostile tone...), and a 4-star review with any "but ... / however ... / wait / rude" cue goes to a person.
  * ONLY NEW REVIEWS: a review is eligible only if Google dated it after `auto_reply_since` (the moment this was switched on) and within the last 3 days. Turning this on never answers
    the back catalogue.
  * NEVER OVER A PERSON: if any reply draft already exists for the review, or Google already shows a reply, nothing is sent.
  * THE SAME GOVERNED PATH as a person's reply (content_exec.govern): emergency stop (platform and business), tenant state, plan feature, one publish at a time, read-back from Google, a
    tamper-evident history. The approval recorded on the action says "template rule", not a person's name, and the owner's screens say "sent automatically".
  * CAPS: the plan's monthly reply allowance (the same pool as AI reply drafts), a per-business daily limit, and a rotation so the same wording is not used twice in a row.
  * OFF SWITCHES: the business's own (Auto-replies, or the autonomy stop), the platform emergency stop, and automatic suspension after repeated failures.
Pure helpers (templates, name cleaning, eligibility of the text) are separate from the database parts so they can be tested without either."""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentSettings, GoogleConnection, GoogleConnectionStatus, GoogleLocation, ReplyDraft, ReplyStatus, Review, Tenant
from app.models.base import utcnow
from app.services import ai_usage
from app.services import consent as consent_svc
from app.services import entitlements as ent
from app.services.ai.safety import assess_risk
from app.services.agent import controls
from app.services.agent.safety import check_text

log = logging.getLogger("flowqr.auto_reply")
RULE = "template_reply_v1"
MAX_AGE = timedelta(days=3)  # a review older than this when it is first seen is left for a person
MAX_TEMPLATES, MIN_LEN, MAX_LEN = 10, 20, 600
PLACEHOLDERS = ("{greeting}", "{business}")

DEFAULT_TEMPLATES = {
    "en": [
        "{greeting}, thank you so much for taking the time to review {business}. We are glad you had a good experience and we look forward to seeing you again.",
        "{greeting}, thank you for your kind words about {business}. It means a lot to our whole team, and we hope to welcome you again soon.",
        "{greeting}, thank you for your review. Feedback like yours encourages everyone at {business}. See you next time!",
        "{greeting}, we really appreciate you sharing your experience with {business}. Thank you for trusting us, and we hope to see you again.",
        "{greeting}, thank you for the lovely review of {business}. We are happy we could help and we are always here when you need us.",
    ],
    "hi": [
        "{greeting}, {business} के बारे में अपनी राय साझा करने के लिए बहुत धन्यवाद। आपका अनुभव अच्छा रहा, यह जानकर हमें खुशी हुई। हम आपका फिर स्वागत करने के लिए उत्सुक हैं।",
        "{greeting}, {business} के लिए आपके अच्छे शब्दों का बहुत धन्यवाद। इससे हमारी पूरी टीम का हौसला बढ़ता है। उम्मीद है जल्द ही फिर मिलेंगे।",
        "{greeting}, आपकी समीक्षा के लिए शुक्रिया। {business} पर भरोसा करने के लिए हम आपके आभारी हैं और आपको दोबारा देखकर खुशी होगी।",
    ],
}
_NEGATIVE_CUES = re.compile(r"\b(but|however|although|though|except|unfortunately|disappoint\w*|wait(ed|ing)?|late|delay\w*|rude|expensive|costly|overpriced|not (so )?(good|great|happy|helpful)|could (have|be) better|"
                            r"issue|problem|complain\w*|poor|bad|worse|worst|dirty|crowded|refund)\b|लेकिन|परंतु|मगर|देर|खराब|महंगा", re.I)
_SKIP_NAMES = {"a", "an", "google", "user", "customer", "anonymous", "guest", "the"}
_UNSAFE = re.compile(r"(https?://|www\.|@|\b\d{5,}\b|\b\d{3,}[\s-]\d{3,}\b)", re.I)
_PROMISE = re.compile(r"\b(guarantee\w*|cure\w*|100\s?%|free|discount\w*|offer\w*|coupon|refund\w*|best in)\b", re.I)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


# ============================================================================================================================ pure helpers
def clean_first_name(reviewer_name: str | None) -> str | None:
    """A first name that is safe to put in a public reply, or None. Google reviewers can use any string; only a plain name of letters is used."""
    if not reviewer_name:
        return None
    first = reviewer_name.strip().split()[0] if reviewer_name.strip() else ""
    first = first.strip(".,;:!?()[]\"'")
    if not (2 <= len(first) <= 20) or first.lower() in _SKIP_NAMES:
        return None
    if not re.fullmatch(r"[A-Za-zऀ-ॿ]+", first):
        return None
    return first.capitalize() if first.isascii() else first


def language_for(review_text: str | None) -> str:
    t = review_text or ""
    letters = [c for c in t if c.isalpha()]
    if letters and sum(1 for c in letters if _DEVANAGARI.match(c)) / len(letters) > 0.3:
        return "hi"
    return "en"


def greeting(name: str | None, lang: str) -> str:
    if lang == "hi":
        return f"प्रिय {name}" if name else "नमस्ते"
    return f"Dear {name}" if name else "Hello"


def validate_template(text: str) -> list[str]:
    """Why an owner's template may not be used, in plain words. [] = fine. The same checks run again on every rendered reply."""
    t = (text or "").strip()
    problems: list[str] = []
    if not MIN_LEN <= len(t) <= MAX_LEN:
        problems.append(f"A template must be {MIN_LEN} to {MAX_LEN} characters.")
    for ph in re.findall(r"\{[^}]*\}", t):
        if ph not in PLACEHOLDERS:
            problems.append(f"Only {{greeting}} and {{business}} can be used, not {ph}.")
    if _UNSAFE.search(t):
        problems.append("A template cannot contain a web address, email address or phone number.")
    if _PROMISE.search(t):
        problems.append("A template cannot promise, guarantee, offer or mention refunds, free items or discounts.")
    if [v for v in check_text(t, kb={}, kind="reply")]:
        problems.append("A template cannot mention prices, discounts or confirm bookings.")
    return problems


def validate_templates(items) -> tuple[list[str], list[str]]:
    """(clean templates, problems). Each problem names the template number."""
    if not isinstance(items, list):
        return [], ["Templates must be a list."]
    if len(items) > MAX_TEMPLATES:
        return [], [f"At most {MAX_TEMPLATES} templates."]
    clean, problems = [], []
    for i, raw in enumerate(items, 1):
        t = " ".join(str(raw).split())
        for p in validate_template(t):
            problems.append(f"Template {i}: {p}")
        clean.append(t)
    return ([] if problems else clean), problems


def templates_for(settings_row: AgentSettings, lang: str) -> list[str]:
    own = [t for t in (settings_row.reply_templates or []) if isinstance(t, str) and not validate_template(t)]
    return own or DEFAULT_TEMPLATES.get(lang) or DEFAULT_TEMPLATES["en"]


def render(template: str, reviewer_name: str | None, business: str, lang: str) -> str:
    return " ".join(template.replace("{greeting}", greeting(clean_first_name(reviewer_name), lang)).replace("{business}", (business or "us").strip()).split())


def choose(templates: list[str], review_key: str, recent_indexes: list[int], reviewer_name: str | None, business: str, lang: str) -> tuple[str, int]:
    """Deterministic for a review (a retry picks the same one), but skips the templates used on the last few replies. Returns (rendered text, template index)."""
    start = int(hashlib.sha256(review_key.encode()).hexdigest(), 16) % len(templates)
    avoid = set(recent_indexes[: max(0, len(templates) - 1)])  # never avoid all of them
    for off in range(len(templates)):
        i = (start + off) % len(templates)
        if i not in avoid:
            return render(templates[i], reviewer_name, business, lang), i
    return render(templates[start], reviewer_name, business, lang), start


def text_is_clearly_positive(rating: int, text: str | None, min_rating: int) -> tuple[bool, str]:
    if rating < min_rating:
        return False, "below the rating this business chose for automatic replies"
    risk = assess_risk(text, rating)
    if risk.level != "low" or risk.reasons:
        return False, "the review needs a person (" + ", ".join(risk.reasons or [risk.level]) + ")"
    if rating == 4 and text and _NEGATIVE_CUES.search(text):
        return False, "a 4-star review with a mixed or critical remark is left for a person"
    return True, ""


# ============================================================================================================================ database parts
def settings_for(db: Session, tenant_id: uuid.UUID) -> AgentSettings:
    from app.services.agent.executor import get_settings

    return get_settings(db, tenant_id)


def month_count(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> int:
    n = now or utcnow()
    start = datetime(n.year, n.month, 1, tzinfo=n.tzinfo)
    return db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.auto_published.is_(True), ReplyDraft.created_at >= start,
                                                                         ReplyDraft.status.in_((ReplyStatus.approved, ReplyStatus.publishing, ReplyStatus.published)))) or 0


def allowance(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> dict:
    """The plan's reply allowance is ONE pool shared by AI reply drafts and automatic template replies."""
    e = ent.for_tenant(db, tenant_id)
    used = ai_usage.usage_this_month(db, tenant_id, field="review_replies") + month_count(db, tenant_id, now)
    return {"cap": e.review_replies, "used": used, "remaining": max(0, e.review_replies - used)}


def master_switch(s: AgentSettings) -> tuple[bool, str]:
    if not s.auto_reply_enabled:
        return False, "automatic replies are switched off for this business"
    if not s.autonomy_enabled or s.autonomy_suspended_at:
        return False, "autonomy is switched off or suspended for this business"
    return True, ""


def still_allowed(db: Session, d: ReplyDraft) -> bool:
    """For a retry of an automatic reply: is the rule STILL permitted for this business (switch, stop, plan allowance, review still unanswered)?"""
    s = settings_for(db, d.tenant_id)
    ok, _ = master_switch(s)
    review = db.get(Review, d.review_id)
    consented = bool(review is not None and consent_svc.has_active(db, d.tenant_id, review.google_location_id, consent_svc.REPLY_SCOPE))
    return bool(ok and consented and review is not None and review.google_reply_text is None and not controls.emergency_stop(db))


def eligibility(db: Session, tenant: Tenant, s: AgentSettings, review: Review, gloc: GoogleLocation, now: datetime) -> tuple[bool, str]:
    ok, why = master_switch(s)
    if not ok:
        return False, why
    if not consent_svc.has_active(db, tenant.id, gloc.id, consent_svc.REPLY_SCOPE):
        return False, "the owner has not given consent for automatic replies at this location"
    if not tenant.is_active or tenant.suspended_at or tenant.deletion_scheduled_for:
        return False, "the business is suspended or being deleted"
    if review.google_reply_text is not None or review.google_reply_state in ("PENDING", "LIVE"):
        return False, "Google already shows a reply"
    if review.review_created_at < s.auto_reply_since or review.review_created_at < now - MAX_AGE:
        return False, "the review is older than the automatic-reply window"
    if db.scalar(select(ReplyDraft.id).where(ReplyDraft.review_id == review.id).limit(1)):
        return False, "a reply already exists for this review"
    good, why = text_is_clearly_positive(review.rating, review.text, s.auto_reply_min_rating)
    if not good:
        return False, why
    if not gloc.selected:
        return False, "the location is not connected"
    return True, ""


def _recent_indexes(db: Session, tenant_id: uuid.UUID, limit: int = 4) -> list[int]:
    return [i for (i,) in db.execute(select(ReplyDraft.template_index).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.auto_published.is_(True), ReplyDraft.template_index.is_not(None))
                                     .order_by(ReplyDraft.created_at.desc()).limit(limit))]


def process_tenant(db: Session, tenant_id: uuid.UUID, *, now: datetime | None = None, provider=None, max_replies: int = 5) -> dict:
    """Answer the eligible reviews of one business. Returns counts and the reasons reviews were left for a person. Never raises for one review's problem."""
    from app.services.agent import content_exec

    now = now or utcnow()
    out = {"sent": 0, "held": 0, "left_for_person": 0, "reasons": {}}
    tenant = db.get(Tenant, tenant_id)
    s = settings_for(db, tenant_id)
    ok, why = master_switch(s)
    if tenant is None or not ok or controls.emergency_stop(db):
        return {**out, "skipped": why or "stopped"}
    day_used = db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.auto_published.is_(True), ReplyDraft.created_at >= now - timedelta(hours=24))) or 0
    room = min(max_replies, max(0, s.auto_reply_daily_limit - day_used))
    cap = allowance(db, tenant_id, now)
    room = min(room, cap["remaining"])
    if room <= 0:
        return {**out, "skipped": "daily limit or the plan's reply allowance is used up", "allowance": cap}
    e = ent.for_tenant(db, tenant_id)
    if not e.active or not e.has("ai_replies"):
        return {**out, "skipped": "the plan does not include replies or is inactive"}
    rows = db.execute(select(Review, GoogleLocation).join(GoogleLocation, GoogleLocation.id == Review.google_location_id)
                      .join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id)
                      .where(Review.tenant_id == tenant_id, Review.google_reply_text.is_(None), Review.rating >= s.auto_reply_min_rating, Review.review_created_at >= s.auto_reply_since,
                             Review.review_created_at >= now - MAX_AGE, GoogleConnection.status == GoogleConnectionStatus.active)
                      .order_by(Review.review_created_at.asc()).limit(room * 4)).all()
    for review, gloc in rows:
        if out["sent"] + out["held"] >= room:
            break
        ok, why = eligibility(db, tenant, s, review, gloc, now)
        if not ok:
            out["left_for_person"] += 1
            out["reasons"][why] = out["reasons"].get(why, 0) + 1
            continue
        lang = language_for(review.text)
        body, idx = choose(templates_for(s, lang), review.external_id, _recent_indexes(db, tenant_id), review.reviewer_name, tenant.name, lang)
        if validate_template(body):  # defence in depth: the rendered text, with a real name in it, passes the same rules
            out["left_for_person"] += 1
            out["reasons"]["the rendered reply failed a safety check"] = out["reasons"].get("the rendered reply failed a safety check", 0) + 1
            continue
        d = ReplyDraft(tenant_id=tenant_id, review_id=review.id, body=body, status=ReplyStatus.approved, language=lang, generated_by_ai=False, requires_human_handling=False, flag_reasons=[],
                       risk_level="low", created_by=None, approved_by=None, approved_at=now, auto_published=True, template_index=idx)
        db.add(d)
        db.flush()
        from app.services.audit import audit

        audit(db, action="reply.auto_template", tenant_id=tenant_id, user_id=None, entity_type="reply_draft", entity_id=d.id, meta={"rule": RULE, "template": idx, "rating": review.rating, "language": lang})
        db.commit()
        try:
            res = content_exec.run(db, "reply", d, provider=provider, now=now)
        except Exception:  # noqa: BLE001 - one review's failure must not stop the rest; the draft stays 'failed' and the retry job decides
            db.rollback()
            log.exception("automatic reply %s failed", d.id)
            out["held"] += 1
            continue
        if res["outcome"] == "held":
            out["held"] += 1
            out["reasons"][res.get("reason") or "held"] = out["reasons"].get(res.get("reason") or "held", 0) + 1
        else:
            out["sent"] += res["outcome"] == "done"
    return out


def run_all(*, now: datetime | None = None, provider=None) -> dict:
    from app.core.db import system_session

    db = system_session()
    total = {"businesses": 0, "sent": 0, "held": 0}
    try:
        if controls.emergency_stop(db):
            return {"stopped": True, **total}
        ids = list(db.scalars(select(Tenant.id).join(AgentSettings, AgentSettings.tenant_id == Tenant.id).where(Tenant.is_active.is_(True), Tenant.suspended_at.is_(None), Tenant.deletion_scheduled_for.is_(None),
                                                                                                              AgentSettings.auto_reply_enabled.is_(True), AgentSettings.autonomy_enabled.is_(True))))
        for tid in ids:
            try:
                r = process_tenant(db, tid, now=now, provider=provider)
                total["businesses"] += 1
                total["sent"] += r.get("sent", 0)
                total["held"] += r.get("held", 0)
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("automatic replies failed for business %s", tid)
        return total
    finally:
        db.close()
