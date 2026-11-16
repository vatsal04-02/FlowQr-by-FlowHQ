import logging
import uuid
from datetime import timedelta

from app.core.db import system_session
from app.models import GoogleLocation
from app.services import google as g
from app.services.google.sync import due_locations, sync_google_location
from app.workers.celery_app import celery_app

log = logging.getLogger("flowqr.tasks")


@celery_app.task(name="flowqr.sync_location", bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_backoff_max=900, retry_jitter=True, max_retries=3)
def sync_location(self, google_location_id: str):
    db = system_session()
    try:
        gloc = db.get(GoogleLocation, uuid.UUID(google_location_id))
        if not gloc:
            return {"status": "missing"}
        return sync_google_location(db, gloc)
    except g.GoogleNotConfigured:
        return {"status": "not_configured"}
    finally:
        db.close()


@celery_app.task(name="flowqr.sync_due_locations")
def sync_due_locations():
    db = system_session()
    try:
        ids = [str(x.id) for x in due_locations(db)]
    finally:
        db.close()
    for gid in ids:
        sync_location.delay(gid)
    return {"queued": len(ids)}


@celery_app.task(name="flowqr.billing_reconcile")
def billing_reconcile():
    """Hourly: Cashfree does not replay missed webhooks, so read and apply the truth for every subscription that is in motion."""
    from app.core.config import settings

    if not settings.cashfree_configured:
        return {"skipped": "cashfree is not configured"}
    from app.services import billing_cashfree as cfb
    from app.services import cashfree

    db = system_session()
    try:
        return cfb.reconcile(db, cashfree.get_cashfree())
    finally:
        db.close()


@celery_app.task(name="flowqr.billing_refresh")
def billing_refresh():
    from app.services.billing import refresh_statuses

    db = system_session()
    try:
        return refresh_statuses(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.purge_review_sessions")
def purge_review_sessions():
    """Delete customer answers and drafts past the retention period (analytics events are kept; they hold no text)."""
    from app.services.review_growth import purge_expired

    db = system_session()
    try:
        return {"purged": purge_expired(db)}
    finally:
        db.close()


@celery_app.task(name="flowqr.auto_replies")
def auto_replies():
    """Answer new, clearly positive reviews from the business's reply template. Every rule is in services/auto_reply.py; sending goes through the governed publisher."""
    from app.services import auto_reply

    return auto_reply.run_all()


@celery_app.task(name="flowqr.retry_failed_replies")
def retry_failed_replies():
    """Re-attempt replies that a human approved but Google rejected for a *transient* reason (429/5xx).

    Never touches unapproved drafts. Row-locked (skip_locked) so overlapping runs or a user clicking Retry can't double-publish.
    """
    from sqlalchemy import select

    from app.core.deps import member_may_act
    from app.models import ReplyDraft, ReplyLog, ReplyStatus, Review, Role
    from app.services import entitlements as ent
    from app.services.agent import content_exec

    from datetime import timedelta as _td

    from app.models.base import utcnow

    from app.services.agent import controls

    db = system_session()
    done = 0
    try:
        if controls.emergency_stop(db):  # platform emergency stop: hold (nothing is failed or lost; it resumes when the stop is lifted)
            return {"stopped": True, "retried": 0}
        # A send that never got Google's answer (worker or API crashed after "publishing" was saved): mark it failed with a reason.
        # Treated like a transient error below, so it is re-sent; Google's reply call is an upsert, so this cannot duplicate a reply.
        for d in db.scalars(select(ReplyDraft).where(ReplyDraft.status == ReplyStatus.publishing, ReplyDraft.updated_at < utcnow() - _td(minutes=10)).with_for_update(skip_locked=True)):
            d.status, d.failure_reason = ReplyStatus.failed, "FlowQR lost contact with Google while sending this reply. It will be sent again."
            db.add(ReplyLog(tenant_id=d.tenant_id, review_id=d.review_id, draft_id=d.id, user_id=None, action="publish_interrupted", success=False,
                            http_status=503, error="interrupted before Google answered", created_at=utcnow()))
        db.commit()
        ids = db.scalars(select(ReplyDraft.id).where(ReplyDraft.status == ReplyStatus.failed, (ReplyDraft.approved_by.is_not(None) | ReplyDraft.auto_published.is_(True)), ReplyDraft.attempts < 4)).all()
        for did in ids:
            d = db.scalar(select(ReplyDraft).where(ReplyDraft.id == did).with_for_update(skip_locked=True))
            if not d or d.status != ReplyStatus.failed:
                continue
            last = db.scalar(select(ReplyLog).where(ReplyLog.draft_id == d.id).order_by(ReplyLog.created_at.desc()).limit(1))
            transient = last is not None and (last.http_status == 429 or (last.http_status or 0) >= 500)
            review = db.get(Review, d.review_id)
            if d.auto_published and d.approved_by is None:  # decided by the template rule: re-check the RULE (switch, stop, still unanswered), not a person
                from app.services import auto_reply

                still_allowed = auto_reply.still_allowed(db, d)
            else:
                still_allowed = member_may_act(db, d.tenant_id, d.approved_by, review.location_id, Role.admin)
            if not transient or review.google_reply_text is not None or not ent.for_tenant(db, d.tenant_id).active or not still_allowed:
                db.rollback()
                continue
            try:
                out = content_exec.run(db, "reply", d, by_user=d.approved_by)  # governed publishing; the existing publisher does the sending
                done += out["outcome"] != "held"
            except Exception:  # keep the worker alive; the draft stays 'failed' for manual retry
                db.rollback()
                log.exception("auto-retry of reply %s failed", did)
        return {"retried": done}
    finally:
        db.close()


@celery_app.task(name="flowqr.purge_deleted_accounts")
def purge_deleted_accounts():
    """Delete businesses whose owner scheduled deletion and whose grace period has ended."""
    from app.services.account import delete_tenant, due_for_deletion

    db = system_session()
    try:
        ids = due_for_deletion(db)
        done = []
        for tid in ids:
            try:
                done.append(delete_tenant(db, tid))
            except Exception:  # keep going: one failure must not block the others, and it retries next hour
                db.rollback()
                log.exception("account deletion failed for %s", tid)
        return {"due": len(ids), "deleted": sum(1 for d in done if d.get("deleted"))}
    finally:
        db.close()


@celery_app.task(name="flowqr.publish_due_posts")
def publish_due_posts():
    """Publish approved posts whose time has come. One post at a time, each in its own transaction, so a slow Google call never
    holds other posts' locks and a crash loses at most the post in hand (it is picked up again, never published twice)."""
    from app.models.base import utcnow
    from app.services import entitlements as ent
    from app.services.agent import content_exec
    from app.services.agent import posts as posts_svc
    from app.services.audit import audit

    from app.services.agent import controls

    db = system_session()
    totals = {"published": 0, "retry": 0, "failed": 0, "skipped": 0, "held": 0}
    try:
        if controls.emergency_stop(db):  # platform emergency stop: posts stay scheduled and publish when it is lifted
            return {**totals, "stopped": True}
        seen: set = set()
        for _ in range(40):
            batch = [p for p in posts_svc.due(db, limit=5) if p.id not in seen]
            if not batch:
                db.rollback()
                break
            p = batch[0]
            seen.add(p.id)
            if not ent.for_tenant(db, p.tenant_id).has("gbp_posts"):
                if p.scheduled_for and p.scheduled_for < utcnow() - timedelta(hours=24):  # a day late: too stale to publish unannounced
                    p.status, p.failure_reason = "failed", "The plan was inactive for more than a day after this post was due, so it was not published. Retry it if it is still relevant."
                    totals["failed"] += 1
                else:
                    totals["held"] += 1
                db.commit()
                continue
            out = content_exec.run(db, "post", p)  # governed publishing; agent/posts.publish does the sending
            res = {"done": "published"}.get(out["outcome"], out["outcome"])
            audit(db, action=f"post.publish_{res}", tenant_id=p.tenant_id, entity_type="scheduled_post", entity_id=p.id, meta={"status": p.status, "reason": p.failure_reason, "scheduled": True})
            totals[res] += 1
            db.commit()
        return totals
    finally:
        db.close()


@celery_app.task(name="flowqr.recover_stuck_posts")
def recover_stuck_posts():
    """Every 5 minutes: posts a worker or API process left in `publishing` (crash, restart, deploy). Google is asked what it really holds; a post
    found there is adopted as published, one that is not there is queued to be sent exactly once. See services/agent/posts.recover_stuck."""
    from app.services.agent import posts as posts_svc

    db = system_session()
    try:
        return posts_svc.recover_stuck(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.autonomy_execute")
def autonomy_execute():
    """Every 2 minutes: execute the profile changes that are authorised and due, through the central executor (policy and approval re-checked at this moment,
    write, read back, history). Holds while the platform emergency stop is on. A business whose autonomy was switched off or suspended has its pending
    autonomous actions returned to "waiting for a person", not executed."""
    from app.services.agent import executor

    db = system_session()
    try:
        return executor.run_due(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.autonomy_housekeeping")
def autonomy_housekeeping():
    """Every 5 minutes: expire proposals and authorisations nobody used in time, and resolve actions a crash left "executing" by reading Google (never by writing again)."""
    from app.services.agent import content_exec, executor

    db = system_session()
    try:
        return {"expired": executor.expire_due(db), "recovered": executor.recover_stuck(db), "recovered_content": content_exec.recover_stuck(db)}
    finally:
        db.close()


@celery_app.task(name="flowqr.autonomy_retention")
def autonomy_retention():
    """Daily: erase finished autonomy records and old map scans past their retention period (docs/DATA_RETENTION.md). Whole records only, counted in the audit log."""
    from app.services.agent import retention

    db = system_session()
    try:
        return retention.purge_old_history(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.autonomy_followups")
def autonomy_followups():
    """Hourly: the 7/14/28-day ranking re-measurements after verified changes, inside each business's Places allowance. Monitoring only: it keeps running when
    execution is stopped."""
    from app.services.agent import learning

    db = system_session()
    try:
        return learning.run_due_followups(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.autonomy_scan")
def autonomy_scan():
    """Every 6 hours, for businesses that switched autonomy on (and are not suspended): look for verified improvements and hand them to the policy engine.
    Proposals only; nothing here writes to Google."""
    from sqlalchemy import select

    from app.models import AgentSettings, Tenant
    from app.services import entitlements as ent
    from app.services.agent import seo_engine

    db = system_session()
    done = {"tenants": 0, "proposed": 0}
    try:
        for s in list(db.scalars(select(AgentSettings).where(AgentSettings.autonomy_enabled.is_(True), AgentSettings.autonomy_suspended_at.is_(None)))):
            t = db.get(Tenant, s.tenant_id)
            if t is None or not t.is_active or t.suspended_at or t.deletion_scheduled_for or not ent.for_tenant(db, t.id).has("autonomy"):
                continue  # no autonomous maintenance without the plan feature
            try:
                r = seo_engine.scan_tenant(db, t)
                db.commit()
                done["tenants"] += 1
                done["proposed"] += r["proposed"]
            except Exception:  # noqa: BLE001 - one business never stops the others
                db.rollback()
                log.exception("autonomy scan failed for tenant %s", s.tenant_id)
        return done
    finally:
        db.close()


@celery_app.task(name="flowqr.daily_agent")
def daily_agent():
    """Once a day per business (from 06:00 local time): refresh what Google says, then build the plan. A failure for one business
    is recorded on its own activity log and never stops the others."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.models import AgentSettings, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Tenant
    from app.models.base import utcnow
    from app.services import entitlements as ent
    from app.services.agent import plan as plan_svc
    from app.services.agent import snapshots as snap_svc

    db = system_session()
    ran = failed = 0
    try:
        for tid in list(db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True), Tenant.suspended_at.is_(None), Tenant.deletion_scheduled_for.is_(None)))):
            try:
                t = db.get(Tenant, tid)
                now_local = utcnow().astimezone(ZoneInfo(t.timezone or "Asia/Kolkata"))
                s = db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tid))
                if now_local.hour < 6 or (s and (not s.daily_plan or s.last_plan_date == now_local.date())) or not ent.for_tenant(db, tid).has("growth_agent"):
                    continue
                for gl in db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
                        GoogleLocation.tenant_id == tid, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)):
                    snap_svc.refresh(db, gl)
                plan_svc.run_plan(db, t)
                ran += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                failed += 1
                log.exception("daily agent failed for tenant %s", tid)
        return {"ran": ran, "failed": failed}
    finally:
        db.close()


@celery_app.task(name="flowqr.notify_by_email")
def notify_by_email():
    """Hourly: one email per person per business with what happened since their last email (Settings › Notifications choices).
    The first run for someone only starts their watermark, so switching this on never mails the past. Unverified emails get nothing."""
    from sqlalchemy import select

    from app.core.config import settings
    from app.models import Membership, Tenant, User
    from app.models.base import utcnow
    from app.services import notifications as nsvc
    from app.services.mailer import send_email

    db = system_session()
    sent = started = 0
    try:
        now = utcnow()
        tenants = db.scalars(select(Tenant).where(Tenant.is_active.is_(True), Tenant.suspended_at.is_(None), Tenant.deletion_scheduled_for.is_(None)))
        for t in list(tenants):
            for m in list(db.scalars(select(Membership).where(Membership.tenant_id == t.id))):
                try:
                    u = db.get(User, m.user_id)
                    if not u or not u.is_active or not u.email_verified_at:
                        continue
                    prefs = nsvc.prefs_for(db, t.id, u.id, create=True)
                    if prefs.last_emailed_at is None:
                        prefs.last_emailed_at = now
                        started += 1
                        db.commit()
                        continue
                    items = nsvc.digest_for(db, t, m, prefs, now)
                    if items:
                        subject, body = nsvc.email_text(t, u, items, settings.frontend_url)
                        if send_email(u.email, subject, body):
                            sent += 1
                    prefs.last_emailed_at = now
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    log.exception("notification email failed for tenant %s user %s", t.id, m.user_id)
        return {"sent": sent, "started": started}
    finally:
        db.close()


@celery_app.task(name="flowqr.publish_due_media")
def publish_due_media():
    """Send approved photos whose time has come (one per transaction, row-locked, never twice), then ask Google again about photos it
    accepted but is not serving yet. Mirrors publish_due_posts."""
    from datetime import timedelta as _td

    from sqlalchemy import select

    from app.models import ScheduledMedia
    from app.models.base import utcnow
    from app.services import entitlements as ent
    from app.services import media as media_svc
    from app.services.agent import content_exec
    from app.services.audit import audit

    from app.services.agent import controls

    db = system_session()
    totals = {"published": 0, "retry": 0, "failed": 0, "skipped": 0, "held": 0, "now_live": 0}
    try:
        if controls.emergency_stop(db):  # platform emergency stop: photos stay scheduled and upload when it is lifted
            return {**totals, "stopped": True}
        seen: set = set()
        for _ in range(20):
            batch = [m for m in media_svc.due(db) if m.id not in seen]
            if not batch:
                db.rollback()
                break
            m = batch[0]
            seen.add(m.id)
            if not ent.for_tenant(db, m.tenant_id).has("gbp_media"):
                totals["held"] += 1
                db.commit()
                continue
            out = content_exec.run(db, "photo", m)  # governed publishing; media.publish does the sending
            res = {"done": "published"}.get(out["outcome"], out["outcome"])
            audit(db, action=f"photo.publish_{res}", tenant_id=m.tenant_id, entity_type="scheduled_media", entity_id=m.id,
                  meta={"status": m.status, "reason": m.failure_reason, "google_media": m.google_media_name})
            totals[res] += 1
            db.commit()
        # Google accepted these but hasn't served them yet: check again at most every 30 minutes, for up to 3 days.
        stale = utcnow() - _td(minutes=30)
        for m in db.scalars(select(ScheduledMedia).where(ScheduledMedia.status == "published", ScheduledMedia.google_url.is_(None),
                                                          ScheduledMedia.published_at > utcnow() - _td(days=3),
                                                          (ScheduledMedia.google_checked_at.is_(None)) | (ScheduledMedia.google_checked_at < stale)).limit(20)):
            try:
                if media_svc.check_processing(db, m):
                    totals["now_live"] += 1
                db.commit()
            except Exception:  # noqa: BLE001 - a failed check only means "ask again later"
                db.rollback()
                log.exception("processing check failed for photo %s", m.id)
        return totals
    finally:
        db.close()



@celery_app.task(name="flowqr.check_rank_grids")
def check_rank_grids():
    """Every 6 hours: re-scan active geo-grids not scanned for settings.rank_grid_auto_days. Monitoring only (it never changes a profile). A scan runs only if the WHOLE
    scan fits the business's plan allowance and the platform cap, so nothing is half-bought; at most 3 scans per run bounds the Google bill."""
    from app.services import entitlements as ent
    from app.services import rank as rank_svc
    from app.services import rank_grid as grid_svc

    if not rank_svc.enabled():
        return {"skipped": "not configured"}
    db = system_session()
    done = {"scanned": 0, "failed": 0, "skipped": 0, "significant": 0}
    try:
        client = rank_svc.get_client()
        for grid, kw, gl in grid_svc.due_scans(db, 12):
            if done["scanned"] + done["failed"] >= 3:
                break
            e = ent.for_tenant(db, gl.tenant_id)
            if not (e.active and "geo_ranking" in e.features):
                done["skipped"] += 1
                continue
            try:
                sc = grid_svc.scan(db, gl, grid, kw, source="auto", client=client)
                db.commit()
            except rank_svc.RankError:  # allowance too small for the whole scan, or not configured: skip, never partially spend
                db.rollback()
                done["skipped"] += 1
                continue
            except Exception:  # noqa: BLE001 - one grid never stops the others
                db.rollback()
                done["failed"] += 1
                log.exception("grid scan failed for %s", grid.id)
                continue
            done["scanned"] += 1
            done["significant"] += bool((sc.change or {}).get("significant"))
        return done
    finally:
        db.close()


@celery_app.task(name="flowqr.check_ranks")
def check_ranks():
    """Re-measure tracked search terms that have not been checked for settings.rank_auto_check_days. Only for businesses whose plan includes
    performance tools, always within each business's monthly allowance (the cost cap), at most 40 Places calls per run. A failed check is
    recorded as a failed check, never as a rank."""
    from app.services import entitlements as ent
    from app.services import rank as rank_svc

    if not rank_svc.enabled():
        return {"skipped": "not configured"}
    db = system_session()
    done = {"checked": 0, "failed": 0, "capped": 0, "skipped": 0}
    try:
        client = rank_svc.get_client()
        capped: set = set()
        for kw, gl in rank_svc.due_keywords(db, 40):
            if gl.tenant_id in capped:
                done["capped"] += 1
                continue
            e = ent.for_tenant(db, gl.tenant_id)
            if not (e.active and "keyword_tracking" in e.features):
                done["skipped"] += 1
                continue
            try:
                row = rank_svc.check_keyword(db, gl, kw, source="auto", client=client)
            except rank_svc.RankError:
                capped.add(gl.tenant_id)  # allowance used up: stop for this business this month
                done["capped"] += 1
                db.rollback()
                continue
            done["checked"] += 1
            done["failed"] += row.status == "error"
            db.commit()
        db.commit()
    finally:
        db.close()
    return done
