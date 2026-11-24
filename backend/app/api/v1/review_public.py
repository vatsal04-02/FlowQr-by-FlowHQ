"""Review Growth (customer side). Unauthenticated, so: rate limited, bot-blocked for AI, no internal IDs in responses, no
tenant data beyond what the customer should see, and customer text only ever stored under an anonymous session.

Customer flow: GET page -> POST generate (their words -> draft, or mode "manual") -> POST regenerate (optional) -> POST approve (customer's final
text) -> POST redirect (record the click, return the Google link). We never post to Google. Every customer gets the same
flow whatever rating or sentiment they give."""
import re
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core import rate_limit
from app.core.rate_limit import client_ip, hit, limit_by_ip, note_miss
from app.models import Location, RetiredCampaignId, ReviewCampaign, ReviewDraft, ReviewEvent, ReviewSession, Tenant
from app.models.base import utcnow
from app.schemas.review_growth import ApproveIn, Customization, GenerateIn, HandoffIn, RedirectIn, RefineIn, RegenerateIn, SubmitIn
from app.services import cards as cards_svc
from app.services.agent import knowledge as kbs
from app.services import review_growth as svc
from app.services.ai import AIUnavailable, get_provider, privacy
from app.services.ai.base import configured_identity
from app.services.review_suggestions import MEANING, SENTIMENTS, follow_up_for, merged_context, topics_for
from app.services.ai import health as ai_health
from app.services.ai.review_generate import (
    CLARIFY, RATING_SENTIMENT, NeedsMoreDetail, ReviewDraftRejected, ReviewInput, clean_field, generate_review, is_too_vague,
)
from app.services.ai_usage import log_generation, metered, quota_exceeded
from app.services.review_submit import SubmitRequest, SubmitUnavailable, provider_for

router = APIRouter(prefix="/public/reviews", tags=["public"])

DISCLAIMER = "AI-assisted draft based only on what you told us. Read it, edit it so it is truly your own words, and only post it if it is accurate."
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
NOT_FOUND = {"state": "not_found", "message": "We couldn't find this page."}


def _live(db: Session, public_id: str):
    """(campaign, tenant, location) for an active campaign, else raises. Unknown ids are 404 and never recorded."""
    campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.public_id == public_id)) if _PUBLIC_ID.match(public_id) else None
    if not campaign and _PUBLIC_ID.match(public_id):
        # An earlier code of a campaign: printed copies keep working and open the campaign as it is today.
        old = db.scalar(select(RetiredCampaignId).where(RetiredCampaignId.public_id == public_id))
        if old and old.deactivated_at is not None:
            raise HTTPException(status_code=410, detail={"state": "deactivated", "message": "This QR code was switched off by the business. Please ask them for a new one."})
        if old:
            campaign = db.get(ReviewCampaign, old.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    tenant = db.get(Tenant, campaign.tenant_id)
    loc = db.get(Location, campaign.location_id) if campaign.location_id else None
    if campaign.status != "active" or not tenant or not tenant.is_active or tenant.suspended_at or not loc or not loc.is_active:
        raise HTTPException(status_code=410, detail={"state": "inactive", "message": "This review page is no longer active."})
    return campaign, tenant, loc


def _session(db: Session, campaign: ReviewCampaign, identifier: str) -> ReviewSession:
    s = db.scalar(select(ReviewSession).where(ReviewSession.campaign_id == campaign.id, ReviewSession.session_identifier == identifier))
    if not s:
        raise HTTPException(status_code=404, detail="Session not found. Please start again.")
    if s.created_at < utcnow() - timedelta(hours=svc.SESSION_VALID_HOURS):
        raise HTTPException(status_code=410, detail="This session has expired. Please start again.")
    return s


def _guard_manual(request: Request, public_id: str) -> tuple[str, str | None]:
    """Opening a manual-writing session makes no AI call, so it gets a looser limit, but real browsers only and still bounded."""
    ip, ua = client_ip(request), request.headers.get("user-agent")
    if cards_svc.is_bot(ua):
        raise HTTPException(status_code=403, detail="Automated requests are not supported.")
    if not hit(f"rman:{ip}:{public_id}", 20, 600) or not hit(f"rman-ip:{ip}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many attempts for now. Please wait a few minutes and try again.")
    return ip, ua


def _guard_ai_request(request: Request, public_id: str) -> tuple[str, str | None]:
    ip, ua = client_ip(request), request.headers.get("user-agent")
    if cards_svc.is_bot(ua):  # protects LLM spend: only real browsers may trigger generation
        raise HTTPException(status_code=403, detail="Automated requests are not supported.")
    if not hit(f"rgen:{ip}:{public_id}", settings.rl_review_generate_per_10min, 600) or not hit(f"rgen-ip:{ip}", 120, 3600):
        raise HTTPException(status_code=429, detail="You've reached the limit for now. You can still write your review in your own words.")
    return ip, ua


@router.get("/{public_id}", dependencies=[Depends(limit_by_ip("rscan", settings.rl_public_scan_per_minute, 60))])
def landing(public_id: str, request: Request, db: Session = Depends(public_db)):
    ip, ua = client_ip(request), request.headers.get("user-agent")
    try:
        campaign, tenant, loc = _live(db, public_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            note_miss(request, "rscan")  # repeated unknown ids from one address = guessing
        raise
    vhash = cards_svc.visitor_hash(ip, ua)
    recent = db.scalar(select(ReviewEvent.id).where(
        ReviewEvent.campaign_id == campaign.id, ReviewEvent.event_type == "scan", ReviewEvent.visitor_hash == vhash,
        ReviewEvent.created_at > utcnow() - timedelta(seconds=20)).limit(1))
    if not recent:  # ignore rapid refreshes
        svc.record_event(db, campaign, "scan", ip=ip, ua=ua)
        db.commit()

    c = Customization.model_validate(campaign.customization or {})
    url, _ = svc.resolve_review_url(db, loc)
    bctx = merged_context(tenant, loc)  # the business, its category and the owner's enabled topics: all resolved from the campaign id, never from the customer
    default_lang = c.default_language if c.default_language in bctx.languages else bctx.languages[0]
    return {
        "state": "ok",
        "suggestions": [{"id": t.id, "en": t.en, "hi": t.hi} for t in bctx.topics],
        "sentiments": [{"id": k, "en": v} for k, v in SENTIMENTS.items()],
        "business": {"name": c.display_name or tenant.name, "category": tenant.category, "logo_url": c.logo_url or tenant.logo_url},
        "location": {"name": loc.name, "city": loc.city, "address": ", ".join(p for p in [loc.address_line, loc.city] if p) or None},
        "branding": {"brand_color": c.brand_color, "background": c.background, "welcome_message": c.welcome_message, "footer_message": c.footer_message},
        "generator": {"styles": c.allowed_styles, "default_style": c.default_style, "default_language": default_lang,
                      "languages": list(bctx.languages), "show_rating": c.show_rating, "max_drafts": settings.review_max_ai_writes_per_session,
                      "max_input_chars": settings.public_ai_max_input_chars},
        "ai_available": settings.ai_configured and privacy.blocked_now() is None and not quota_exceeded(db, tenant.id, "review_generate") and ai_health.current() is None,
        "google_ready": bool(url),
        "review_url": url,  # the business's own public Google link: the page opens it straight from the customer's tap (never gated by rating)
        "review_url_kind": svc.review_url_kind(url),
        "submission": {"mode": (sub := provider_for(loc)).mode, **sub.capabilities()},  # "handoff" today: Google offers no public way to submit for a customer
        "disclaimer": DISCLAIMER,
        "whatsapp_optin": _whatsapp_optin(db, tenant),  # an optional click-to-chat link to the business's own number; nothing is collected on this page
    }


def _whatsapp_optin(db, tenant):
    try:
        from app.services.whatsapp import optin
        link = optin.public_link(db, tenant)
        return {"url": link["url"], "purpose_words": link["purpose_words"]} if link else None
    except Exception:  # noqa: BLE001 - the review page must never fail because of an optional add-on
        return None


RETRYABLE = {"rate_limited", "timeout", "provider_error", "bad_response", "tls", "rejected"}  # "try again" can plausibly work
UNAVAILABLE_MESSAGE = "Writing help isn't available right now. You can write your review in your own words."


def _require_ai_write(draft: ReviewDraft) -> None:
    """Every customer visit gets a fixed number of AI-written versions (2 by default), however they ask for them. Checked BEFORE anything is changed or any model is called."""
    n = settings.review_max_ai_writes_per_session
    if (draft.ai_writes or 0) >= n:
        raise HTTPException(status_code=429, detail=f"You've used your {n} AI-written versions. Tap Edit to change the text, or write your own words.")


def _draft_payload(session: ReviewSession | None, draft: ReviewDraft | None, *, ai_status: str, message: str | None = None,
                   retryable: bool = False, language: str = "en") -> dict:
    """What the page needs after a generate/regenerate. `ai_status`: ok | manual | needs_more | rejected | unavailable.
    `retryable` tells the page whether offering "Try again" makes sense; it never carries provider detail."""
    count = draft.generation_count if draft else 0
    return {
        "session_id": session.session_identifier if session else None, "draft": draft.generated_content if draft else None,
        "ai_status": ai_status, "message": message, "retryable": retryable,
        "generation_count": count, "remaining_drafts": max(0, min(settings.review_max_drafts_per_session - count, settings.review_max_ai_writes_per_session - ((draft.ai_writes or 0) if draft else 0))),
        "style": session.style if session else None, "language": session.language if session else language, "disclaimer": DISCLAIMER,
    }


def _describing(words: tuple[str, ...], sentiment: str | None) -> str:
    """Describing words offered to the writer for one topic, matched to the direction of the rating."""
    if not words:
        return ""
    if sentiment == "good":
        return f" Describing words that fit (use at most a couple, vary them): {', '.join(words)}."
    if sentiment == "not_good":
        return f" Only if needed, you may negate one of: {', '.join(words)} (for example 'not explained clearly'). Never use them positively."
    return ""


def recent_reviews(db: Session, tenant, campaign, session: ReviewSession, limit: int = 10) -> tuple[str, ...]:
    """What other customers of this location were recently given, so each new review can be written to read differently (and is rejected if it is too close). Only drafts built from
    stars and topics are used: a draft that contains someone's own typed words is never sent to the AI as an example for another customer."""
    camp_ids = select(ReviewCampaign.id).where(ReviewCampaign.tenant_id == tenant.id, ReviewCampaign.location_id == campaign.location_id)
    rows = db.execute(select(ReviewDraft.generated_content, ReviewSession.customer_input).join(ReviewSession, ReviewSession.id == ReviewDraft.session_id)
                      .where(ReviewSession.tenant_id == tenant.id, ReviewSession.campaign_id.in_(camp_ids), ReviewDraft.session_id != session.id,
                             ReviewDraft.generated_content.is_not(None)).order_by(ReviewDraft.updated_at.desc()).limit(limit * 3)).all()
    out = [text for text, ci in rows if text and not (ci or {}).get("text") and not (ci or {}).get("details")]
    return tuple(reversed(out[:limit]))


def _context_with_voice(db: Session, tenant, bctx) -> str:
    """The business context for the writer, plus the owner's saved brand tone when there is one (tone only: it adds no facts about the customer's visit)."""
    block = bctx.prompt_block()
    try:
        voice = (kbs.context(db, tenant).get("brand_voice") or "").strip()
    except Exception:
        voice = ""
    voice = " ".join(voice.split())[:120]
    return block + (f"\nOwner's preferred tone (wording style only, never facts): {voice}." if voice else "")


def _run_generation(db: Session, campaign, tenant, loc, session: ReviewSession, draft: ReviewDraft, *, ip: str, ua: str | None, refine: bool = False) -> dict:
    """Ask the provider for a draft. A failure here never blocks the customer: they can write their own words. `refine`: the customer changed their stars,
    topics or words, so rewrite from the new inputs (no "must differ from the last draft" rule, and it does not use up their Regenerate allowance)."""
    started = time.monotonic()
    ci = session.customer_input or {}
    bctx = merged_context(tenant, loc)
    chosen = [t for t in topics_for(bctx.category_key) if t.id in (ci.get("suggestions") or [])]  # looked up in the full category list: stays valid if the owner later disables a chip
    sentiment = RATING_SENTIMENT.get(session.rating) or ci.get("sentiment")  # the rating is stored on the session, so regenerating keeps it
    meanings = [(t, MEANING.get(t.id)) for t in chosen]
    inp = ReviewInput(**{k: ci.get(k, "") for k in ("service", "appreciated", "details")}, note=ci.get("text", ""), rating=session.rating,
                      topics=tuple(t.en for t in chosen), topic_alts=tuple(a for t in chosen for a in t.alts), sentiment=sentiment,
                      topic_notes=tuple(f"{t.en}: {m.about}." + _describing(m.words, sentiment) for t, m in meanings if m),
                      topic_ok=tuple(w for _, m in meanings if m for w in m.words) if sentiment != "okay" else (),  # a neutral review uses no describing words at all
                      topic_hi=tuple(t.hi for t in chosen))
    previous = () if refine else tuple(p for p in (draft.generated_content,) if p)
    recent = recent_reviews(db, tenant, campaign, session)
    first = draft.generation_count == 0

    provider = None
    stats: dict = {}

    def log(status: str, error: str | None = None, out_chars: int = 0):
        name, model = (provider.name, provider.model) if provider else configured_identity()
        log_generation(db, tenant_id=tenant.id, kind="review_generate", provider=name, model=model, language=session.language,
                       input_chars=len(inp.text()), output_chars=out_chars, status=status, started=started, location_id=loc.id, error=error,
                       usage=getattr(provider, "usage", None), stats=stats)  # a rejected draft still cost tokens

    def fail(status: str, message: str, ai_status: str, error: str, retryable: bool):
        log(status, error)
        svc.record_event(db, campaign, "generation_failed", ip=ip, ua=ua, session=session)
        db.commit()
        return _draft_payload(session, draft, ai_status=ai_status, message=message, retryable=retryable)

    if quota_exceeded(db, tenant.id, "review_generate"):
        return fail("error", UNAVAILABLE_MESSAGE, "unavailable", "quota or subscription", False)
    paused = ai_health.current()
    if paused:  # a known-bad provider state: don't make the customer wait for a call that will fail
        return fail("error", UNAVAILABLE_MESSAGE, "unavailable", f"paused: {paused['code']}", False)
    try:
        provider = metered(get_provider(), db, tenant.id, "review_generate")
        text = generate_review(provider, inp, language=session.language, style=session.style, business_name=tenant.name,
                               category=tenant.category, location_name=loc.name, previous=previous, recent=recent,
                               context_text=_context_with_voice(db, tenant, bctx), offered_terms=bctx.offered_terms(), stats=stats)
    except NeedsMoreDetail:
        log("needs_more")
        svc.record_event(db, campaign, "needs_more", ip=ip, ua=ua, session=session)
        db.commit()
        return _draft_payload(session, draft, ai_status="needs_more", message=CLARIFY[session.language])
    except ReviewDraftRejected as exc:
        return fail("rejected", "We couldn't write a draft that stays faithful to what you wrote. You can try again or write it yourself.", "rejected", exc.reason, True)
    except AIUnavailable as exc:
        ai_health.mark_down(exc.code, exc.retry_after)
        # the admin sees the code in logs/analytics; the customer only ever sees a friendly message (no provider detail)
        return fail("error", UNAVAILABLE_MESSAGE, "unavailable", f"{exc.code}: {exc}", exc.code in RETRYABLE)

    ai_health.clear()
    draft.generated_content, draft.ai_assisted = text, True
    draft.ai_writes = (draft.ai_writes or 0) + 1  # a version the customer actually received (a failed attempt never gets here)
    log("ok", None, len(text))
    if first or not refine:  # a refinement after the first draft is neither a new draft nor a "Regenerate" in the numbers
        draft.generation_count += 1
        svc.record_event(db, campaign, "draft_generated" if first else "draft_regenerated", ip=ip, ua=ua, session=session)
    db.commit()
    out = _draft_payload(session, draft, ai_status="ok")
    # One optional question, only when they gave very little (a single topic, no words). The draft is already written: answering is never required.
    out["follow_up"] = follow_up_for([t.id for t in chosen], session.rating, session.language, inp.free_text())
    return out


def _create_session(db: Session, campaign, tenant, *, language: str, style: str, customer_input: dict, rating: int | None, picked: list[str], manual: bool,
                    ip: str, ua: str | None) -> tuple[ReviewSession, ReviewDraft]:
    session = ReviewSession(
        tenant_id=tenant.id, campaign_id=campaign.id, session_identifier=svc.new_session_identifier(), language=language, style=style,
        customer_input=customer_input, rating=rating, created_at=utcnow(),
    )
    db.add(session)
    db.flush()
    draft = ReviewDraft(tenant_id=tenant.id, session_id=session.id, generation_count=0)
    db.add(draft)
    svc.record_event(db, campaign, "feedback_submitted", ip=ip, ua=ua, session=session, rating=rating)  # "started a review", either path; the rating is a bare number
    svc.record_event(db, campaign, "manual_selected" if manual else "ai_requested", ip=ip, ua=ua, session=session)
    for topic_id in picked:  # one event per topic picked: which topics customers choose most often (ids only, no text)
        svc.record_event(db, campaign, "suggestion_selected", ip=ip, ua=ua, session=session, suggestion_id=topic_id)
    db.commit()  # what they wrote is kept even if the AI step fails
    return session, draft


@router.post("/{public_id}/generate")
def generate(public_id: str, body: GenerateIn, request: Request, db: Session = Depends(public_db)):
    """Start a customer session. mode "ai": draft a review from their words. mode "manual": open a session for a review they write
    themselves (no AI call at all)."""
    manual = body.mode == "manual"
    ip, ua = _guard_manual(request, public_id) if manual else _guard_ai_request(request, public_id)
    campaign, tenant, loc = _live(db, public_id)
    c = Customization.model_validate(campaign.customization or {})
    style = body.style if body.style in c.allowed_styles else c.default_style
    bctx = merged_context(tenant, loc)
    language = body.language if body.language in bctx.languages else bctx.languages[0]
    picked = [s for s in dict.fromkeys(body.suggestions) if s in {t.id for t in bctx.topics}]  # only chips this business offers (a stale page may send a disabled one)
    text = clean_field(body.text, 1200)
    legacy = {k: clean_field(getattr(body, k), n) for k, n in (("service", 300), ("appreciated", 500), ("details", 600))}
    customer_input = {**legacy, **({"text": text} if text else {})} if any(legacy.values()) else {"text": text}
    sentiment = RATING_SENTIMENT.get(body.rating) or body.sentiment  # the stars decide the direction (1-2 negative, 3 neutral/mixed, 4-5 positive)
    if picked:
        customer_input["suggestions"] = picked
        if sentiment:
            customer_input["sentiment"] = sentiment
    typed = " ".join([text, *legacy.values()]).strip()

    if not manual and not picked and not typed:
        raise HTTPException(status_code=422, detail="Pick at least one thing that applies, or write a few words about your visit first.")
    if not manual and not picked and is_too_vague(typed):  # too little to write anything truthful (the stars say how it was, not what happened)
        # Ask one small question. No session, no AI call, nothing stored.
        svc.record_event(db, campaign, "ai_requested", ip=ip, ua=ua)
        svc.record_event(db, campaign, "needs_more", ip=ip, ua=ua)
        db.commit()
        out = _draft_payload(None, None, ai_status="needs_more", message=CLARIFY[language], language=language)
        out["ask"] = "detail"
        return out

    session, draft = _create_session(db, campaign, tenant, language=language, style=style, customer_input=customer_input, rating=body.rating, picked=picked,
                                     manual=manual, ip=ip, ua=ua)
    if manual:
        return _draft_payload(session, draft, ai_status="manual")
    return _run_generation(db, campaign, tenant, loc, session, draft, ip=ip, ua=ua)

@router.post("/{public_id}/regenerate")
def regenerate(public_id: str, body: RegenerateIn, request: Request, db: Session = Depends(public_db)):
    ip, ua = _guard_ai_request(request, public_id)
    campaign, tenant, loc = _live(db, public_id)
    session = _session(db, campaign, body.session_id)
    draft = db.scalar(select(ReviewDraft).where(ReviewDraft.session_id == session.id))
    if draft.approved_at:
        raise HTTPException(status_code=409, detail="You've already confirmed your review.")
    _require_ai_write(draft)
    if draft.generation_count >= settings.review_max_drafts_per_session:
        raise HTTPException(status_code=429, detail=f"You've used all {settings.review_max_drafts_per_session} drafts. Please edit the one you like best.")
    c = Customization.model_validate(campaign.customization or {})
    if body.style and body.style in c.allowed_styles:
        session.style = body.style
    if body.language and body.language in merged_context(tenant, loc).languages:
        session.language = body.language
    return _run_generation(db, campaign, tenant, loc, session, draft, ip=ip, ua=ua)


@router.post("/{public_id}/refine")
def refine(public_id: str, body: RefineIn, request: Request, db: Session = Depends(public_db)):
    """The customer picked or changed stars/topics/words after the page already has a session: rewrite the draft from the new inputs, in the same
    session. It does not create another session or "AI help" event, and does not use up Regenerate. The page asks before replacing text they edited."""
    ip, ua = _guard_ai_request(request, public_id)
    campaign, tenant, loc = _live(db, public_id)
    session = _session(db, campaign, body.session_id)
    draft = db.scalar(select(ReviewDraft).where(ReviewDraft.session_id == session.id))
    _require_ai_write(draft)
    ci = dict(session.customer_input or {})
    if int(ci.get("refinements") or 0) >= settings.review_max_refinements:
        raise HTTPException(status_code=429, detail="You've changed your answers a lot. Please edit the text directly, or write your own review.")
    bctx = merged_context(tenant, loc)
    if body.language and body.language in bctx.languages:
        session.language = body.language
    picked = [s for s in dict.fromkeys(body.suggestions) if s in {t.id for t in bctx.topics}]
    text = clean_field(body.text, 1200)
    if not picked and is_too_vague(text):
        raise HTTPException(status_code=422, detail="Pick at least one thing that applies, or write a few words first.")
    for topic_id in (s for s in picked if s not in (ci.get("suggestions") or [])):  # topics newly chosen: counted once each, ids only
        svc.record_event(db, campaign, "suggestion_selected", ip=ip, ua=ua, session=session, suggestion_id=topic_id)
    ci["text"], ci["refinements"] = text, int(ci.get("refinements") or 0) + 1
    if picked:
        ci["suggestions"], ci["sentiment"] = picked, RATING_SENTIMENT[body.rating]
    else:
        ci.pop("suggestions", None); ci.pop("sentiment", None)
    session.customer_input, session.rating = ci, body.rating  # reassigned (not mutated) so the JSON change is saved
    started = db.scalar(select(ReviewEvent).where(ReviewEvent.session_id == session.id, ReviewEvent.event_type == "feedback_submitted").limit(1))
    if started:
        started.rating = body.rating  # the distribution counts the rating they ended with, not the first star they tapped
    db.commit()
    return _run_generation(db, campaign, tenant, loc, session, draft, ip=ip, ua=ua, refine=True)


@router.post("/{public_id}/approve", dependencies=[Depends(limit_by_ip("rapprove", 60, 60))])
def approve(public_id: str, body: ApproveIn, request: Request, db: Session = Depends(public_db)):
    """The customer's confirmed wording (their own, possibly edited). Returns the Google link for them to continue."""
    ip, ua = client_ip(request), request.headers.get("user-agent")
    campaign, _tenant, loc = _live(db, public_id)
    session = _session(db, campaign, body.session_id)
    draft = db.scalar(select(ReviewDraft).where(ReviewDraft.session_id == session.id))
    first = draft.approved_at is None
    draft.final_content, draft.approved_at = body.final_text, draft.approved_at or utcnow()
    if first:
        svc.record_event(db, campaign, "draft_approved", ip=ip, ua=ua, session=session)
    db.commit()
    url, _ = svc.resolve_review_url(db, loc)
    return {"final_text": draft.final_content, "review_url": url, "google_ready": bool(url),
            "next": "Copy your review, tap Continue to Google, then paste it and choose your own star rating. You post it yourself."}


def _confirm_final(db: Session, campaign, tenant, loc, *, public_id: str, session_id: str | None, final_text: str, rating: int | None, suggestions: list[str],
                   language: str, ip: str, ua: str | None) -> tuple[ReviewSession, ReviewDraft]:
    """The customer's own final wording becomes the confirmed review: reuse their session (or open a fresh one if they never asked for AI help, or it
    expired: a tap must never be lost), and record the confirmation once."""
    session = draft = None
    if session_id:
        try:
            session = _session(db, campaign, session_id)
            draft = db.scalar(select(ReviewDraft).where(ReviewDraft.session_id == session.id))
        except HTTPException as exc:
            if exc.status_code not in (404, 410):
                raise
    if session is None:
        if not hit(f"rman:{ip}:{public_id}", 20, 600) or not hit(f"rman-ip:{ip}", 60, 3600):
            raise HTTPException(status_code=429, detail="Too many attempts for now. Please wait a few minutes and try again.")
        bctx = merged_context(tenant, loc)
        c = Customization.model_validate(campaign.customization or {})
        picked = [s for s in dict.fromkeys(suggestions) if s in {t.id for t in bctx.topics}]
        ci: dict = {"text": final_text[:1200]}
        if picked:
            ci["suggestions"] = picked
            if rating:
                ci["sentiment"] = RATING_SENTIMENT[rating]
        session, draft = _create_session(db, campaign, tenant, language=language if language in bctx.languages else bctx.languages[0], style=c.default_style,
                                         customer_input=ci, rating=rating, picked=picked, manual=True, ip=ip, ua=ua)
    first = draft.approved_at is None
    draft.final_content, draft.approved_at = final_text, draft.approved_at or utcnow()
    if first:
        svc.record_event(db, campaign, "draft_approved", ip=ip, ua=ua, session=session)
    return session, draft


@router.post("/{public_id}/handoff", dependencies=[Depends(limit_by_ip("rhandoff", 60, 60))])
def handoff(public_id: str, body: HandoffIn, request: Request, db: Session = Depends(public_db)):
    """The one tap (Copy & Continue to Google) in ONE request: confirm the customer's own final wording, open a session if they never asked for AI help,
    and count the tap once. Nothing is submitted to Google; this only records what the customer chose to do. The link is returned for the record,
    but the page already opened it natively from their tap."""
    ip, ua = client_ip(request), request.headers.get("user-agent")
    if cards_svc.is_bot(ua):
        raise HTTPException(status_code=403, detail="Automated requests are not supported.")
    campaign, tenant, loc = _live(db, public_id)
    session, draft = _confirm_final(db, campaign, tenant, loc, public_id=public_id, session_id=body.session_id, final_text=body.final_text, rating=body.rating,
                                    suggestions=body.suggestions, language=body.language, ip=ip, ua=ua)
    url, _ = svc.resolve_review_url(db, loc)
    seen = db.scalar(select(ReviewEvent.id).where(ReviewEvent.session_id == session.id, ReviewEvent.event_type == "google_redirect").limit(1))
    if url and not seen:
        svc.record_event(db, campaign, "google_redirect", ip=ip, ua=ua, session=session)
        if body.copied:  # the browser said the text reached the clipboard (a yes/no, never the text)
            svc.record_event(db, campaign, "review_copied", ip=ip, ua=ua, session=session)
    db.commit()
    return {"session_id": session.session_identifier, "review_url": url, "google_ready": bool(url), "copied": bool(body.copied)}


@router.post("/{public_id}/submit", dependencies=[Depends(limit_by_ip("rsubmit", 30, 60))])
def submit(public_id: str, body: SubmitIn, request: Request, db: Session = Depends(public_db)):
    """Submit the customer's approved review to Google from inside FlowQR, when (and only when) an approved provider is enabled for this location.

    Today none is: Google offers no public way to create a review, so this answers 409 and the page keeps the supported route (copy + Google's own
    Write-a-review page). When a provider exists the rules still hold here, not in the provider: explicit consent for this exact text (validated and
    recorded), the customer's own wording, the rating accepted as given (equal access), a double tap never submits twice, and success is reported
    ONLY when the provider returns Google's confirmation reference."""
    ip, ua = client_ip(request), request.headers.get("user-agent")
    if cards_svc.is_bot(ua):
        raise HTTPException(status_code=403, detail="Automated requests are not supported.")
    campaign, tenant, loc = _live(db, public_id)
    provider = provider_for(loc)
    if provider.mode != "direct":
        raise HTTPException(status_code=409, detail={"code": "direct_unavailable", "message": "Submitting from here isn't available. Copy your review and post it on Google yourself."})
    session, draft = _confirm_final(db, campaign, tenant, loc, public_id=public_id, session_id=body.session_id, final_text=body.final_text, rating=body.rating,
                                    suggestions=body.suggestions, language=body.language, ip=ip, ua=ua)
    url, _ = svc.resolve_review_url(db, loc)
    done = db.scalar(select(ReviewEvent.id).where(ReviewEvent.session_id == session.id, ReviewEvent.event_type == "review_submitted").limit(1))
    if done:  # a double tap or a retry must never post a second review
        db.commit()
        return {"status": "published", "published": True, "already": True, "session_id": session.session_identifier, "review_url": url}
    fallback = {"code": "submit_failed", "message": "We couldn't submit your review. Copy it and post it on Google yourself.", "review_url": url}
    try:
        result = provider.submit(SubmitRequest(tenant_id=tenant.id, location_id=loc.id, rating=body.rating, text=body.final_text, language=body.language))
    except SubmitUnavailable as exc:
        svc.record_event(db, campaign, "review_submit_failed", ip=ip, ua=ua, session=session)
        db.commit()
        raise HTTPException(status_code=503, detail={**fallback, "code": exc.code})
    except Exception:  # a provider bug or outage never loses the customer's review or claims success
        svc.record_event(db, campaign, "review_submit_failed", ip=ip, ua=ua, session=session)
        db.commit()
        raise HTTPException(status_code=502, detail=fallback)
    published = result.status == "published" and bool(result.external_ref)  # no confirmation reference from Google, no "published"
    svc.record_event(db, campaign, "review_submitted" if published else "review_submit_failed", ip=ip, ua=ua, session=session)
    db.commit()
    return {"status": "published" if published else ("pending" if result.status == "pending" else "failed"), "published": published,
            "message": None if published else fallback["message"], "session_id": session.session_identifier, "review_url": url}


@router.post("/{public_id}/redirect", dependencies=[Depends(limit_by_ip("rredirect", 60, 60))])
def redirect(public_id: str, body: RedirectIn, request: Request, db: Session = Depends(public_db)):
    """Record that the customer tapped Continue to Google (once per session). This is NOT proof a review was published."""
    ip, ua = client_ip(request), request.headers.get("user-agent")
    campaign, _tenant, loc = _live(db, public_id)
    session = _session(db, campaign, body.session_id)
    draft = db.scalar(select(ReviewDraft).where(ReviewDraft.session_id == session.id))
    if not draft or not draft.approved_at:
        raise HTTPException(status_code=409, detail="Please confirm your review first.")
    url, _ = svc.resolve_review_url(db, loc)
    if not url:
        raise HTTPException(status_code=409, detail={"code": "no_review_url", "message": "This business hasn't added its Google review link yet."})
    seen = db.scalar(select(ReviewEvent.id).where(ReviewEvent.session_id == session.id, ReviewEvent.event_type == "google_redirect").limit(1))
    if not seen:
        svc.record_event(db, campaign, "google_redirect", ip=ip, ua=ua, session=session)
        if body.copied:  # the browser reported that the review reached the clipboard before Google opened (a yes/no, never the text)
            svc.record_event(db, campaign, "review_copied", ip=ip, ua=ua, session=session)
        db.commit()
    return {"review_url": url}
