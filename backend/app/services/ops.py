"""Operations checks for FlowHQ administrators: is the platform healthy, and what needs a person?

Every check returns one row: {id, label, status, detail, action}. status is ok | warn | critical | unknown.
`unknown` means "could not be measured" (never shown as healthy). Nothing here exposes customer content or secrets: only counts,
timestamps and settings names an admin can already see.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import config_problems, settings
from app.models import (
    AIGenerationLog, GoogleConnection, GoogleConnectionStatus, GoogleLocation, RankCheck, ReplyDraft, ReplyStatus, ScheduledMedia, ScheduledPost, Subscription,
)
from app.models.base import utcnow

HEARTBEAT_KEY = "flowqr:ops:heartbeat"
TASKS_KEY = "flowqr:ops:tasks"
ALERT_KEY = "flowqr:ops:alert_state"
RANK = {"ok": 0, "unknown": 1, "warn": 2, "critical": 3}
ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def row(id_: str, label: str, status: str, detail: str, action: str = "") -> dict:
    return {"id": id_, "label": label, "status": status, "detail": detail, "action": action}


def _redis():
    try:
        import redis

        c = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        c.ping()
        return c
    except Exception:
        return None


# ---- worker/scheduler heartbeat and per-task outcomes (written by app.workers.monitor)
def record_heartbeat() -> None:
    r = _redis()
    if r:
        r.set(HEARTBEAT_KEY, str(time.time()), ex=3600)


def record_task(name: str, ok: bool, error: str | None = None) -> None:
    r = _redis()
    if not r:
        return
    now = time.time()
    try:
        cur = json.loads(r.hget(TASKS_KEY, name) or "{}")
    except ValueError:
        cur = {}
    if ok:
        cur["ok_at"] = now
    else:
        cur["fail_at"] = now
        cur["error"] = (error or "")[:80]  # exception class only: customer text never goes into this
        cur["fails"] = int(cur.get("fails", 0)) + 1
    r.hset(TASKS_KEY, name, json.dumps(cur))
    r.expire(TASKS_KEY, 7 * 86400)


def _ago(seconds: float) -> str:
    s = int(seconds)
    return f"{s}s" if s < 120 else f"{s // 60} min" if s < 7200 else f"{s // 3600} h"


# ---- individual checks
def check_database(db: Session) -> dict:
    t = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        return row("database", "Database", "critical", f"Query failed ({type(exc).__name__})", "Check the db container and DATABASE_URL.")
    ms = int((time.monotonic() - t) * 1000)
    return row("database", "Database", "ok" if ms < 500 else "warn", f"Responding in {ms} ms")


def check_redis() -> dict:
    return row("redis", "Redis", "ok", "Responding") if _redis() else row("redis", "Redis", "critical", "Not reachable", "Queues, rate limits and the heartbeat need Redis.")


def check_migrations(db: Session) -> dict:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", str(ALEMBIC_DIR))
        heads = set(ScriptDirectory.from_config(cfg).get_heads())
        with db.begin_nested():  # a refused read must not poison the caller's transaction
            current = {r[0] for r in db.execute(text("SELECT version_num FROM alembic_version"))}
    except Exception as exc:
        return row("migrations", "Database migrations", "unknown", f"Could not compare ({type(exc).__name__})")
    if current == heads:
        return row("migrations", "Database migrations", "ok", f"At head ({', '.join(sorted(heads))})")
    return row("migrations", "Database migrations", "critical", f"Database is at {', '.join(sorted(current)) or 'nothing'}, code expects {', '.join(sorted(heads))}",
               "Run the migrate service (docker compose up migrate) before serving traffic.")


def check_heartbeat() -> dict:
    r = _redis()
    if not r:
        return row("worker", "Worker and scheduler", "unknown", "Redis is down, so the heartbeat cannot be read")
    raw = r.get(HEARTBEAT_KEY)
    if not raw:
        return row("worker", "Worker and scheduler", "critical", "No heartbeat has been recorded", "Start the worker and beat containers; check `docker compose logs beat worker`.")
    age = time.time() - float(raw)
    if age <= 180:
        return row("worker", "Worker and scheduler", "ok", f"Beat scheduled and the worker ran a job {_ago(age)} ago")
    return row("worker", "Worker and scheduler", "critical" if age > 600 else "warn", f"Last heartbeat {_ago(age)} ago",
               "Beat or the worker has stopped. Reviews, posts and photos are not being processed.")


def check_task_failures() -> list[dict]:
    r = _redis()
    if not r:
        return []
    try:
        data = {k.decode(): json.loads(v) for k, v in r.hgetall(TASKS_KEY).items()}
    except Exception:
        return []
    now = time.time()
    bad = [(n, d) for n, d in data.items() if d.get("fail_at") and now - d["fail_at"] < 86400 and d.get("fail_at", 0) > d.get("ok_at", 0)]
    if not bad:
        return [row("tasks", "Scheduled jobs", "ok", f"{len(data)} job types seen; none failing at their last run")]
    return [row("tasks", "Scheduled jobs", "critical" if len(bad) > 2 else "warn",
                "Failing at their last run: " + ", ".join(f"{n.removeprefix('flowqr.')} ({d.get('error') or 'error'})" for n, d in bad[:5]),
                "Open the worker logs for these jobs. They retry on their schedule.")]


def check_failed_work(db: Session) -> dict:
    since = utcnow() - timedelta(hours=24)
    replies = db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.status == ReplyStatus.failed, ReplyDraft.updated_at >= since)) or 0
    posts = db.scalar(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.status == "failed", ScheduledPost.updated_at >= since)) or 0
    media = db.scalar(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.status == "failed", ScheduledMedia.updated_at >= since)) or 0
    sync = db.scalar(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.selected.is_(True), GoogleLocation.last_sync_status == "error")) or 0
    total = replies + posts + media + sync
    if total == 0:
        return row("failed_work", "Failed publishing and sync", "ok", "Nothing failed in the last 24 h")
    return row("failed_work", "Failed publishing and sync", "critical" if total >= 10 else "warn",
               f"Last 24 h: {replies} replies, {posts} posts, {media} photos failed to publish; {sync} locations failing to sync",
               "Each owner sees the reason on their Activity page; widespread failures usually mean Google access or quota.")


def check_google_access(db: Session) -> list[dict]:
    bad = db.scalar(select(func.count()).select_from(GoogleConnection).where(GoogleConnection.status.in_((GoogleConnectionStatus.revoked, GoogleConnectionStatus.error)))) or 0
    active = db.scalar(select(func.count()).select_from(GoogleConnection).where(GoogleConnection.status == GoogleConnectionStatus.active)) or 0
    out = [row("google_tokens", "Google connections", "warn" if bad else "ok",
               f"{active} active; {bad} revoked or in error (owners must reconnect)" if bad else f"{active} active, none revoked",
               "Revoked or expired Google access: owners are told in the app. If many fail at once, check that the OAuth consent screen is published "
               "(a 'Testing' app expires refresh tokens after 7 days)." if bad else "")]
    waiting = db.scalar(select(func.count()).select_from(GoogleConnection).where(GoogleConnection.api_access == "awaiting_approval")) or 0
    limited = db.scalar(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.selected.is_(True), GoogleLocation.last_sync_status == "rate_limited")) or 0
    if waiting or limited:
        out.append(row("google_quota", "Google API quota", "warn", f"{waiting} connections await Business Profile API approval; {limited} locations rate-limited",
                       "Request or confirm Business Profile API access and quota in Google Cloud Console."))
    else:
        out.append(row("google_quota", "Google API quota", "ok", "No rate limiting or pending approval seen"))
    return out


def month_start() -> datetime:
    n = utcnow()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def ai_spend(db: Session) -> dict:
    """This month's platform AI spend: provider-reported cost where there is one, else tokens x configured prices (0 = unknown)."""
    calls, reported, tin, tout, unpriced = db.execute(
        select(func.count(), func.coalesce(func.sum(AIGenerationLog.cost_usd), 0), func.coalesce(func.sum(AIGenerationLog.prompt_tokens).filter(AIGenerationLog.cost_usd.is_(None)), 0),
               func.coalesce(func.sum(AIGenerationLog.completion_tokens).filter(AIGenerationLog.cost_usd.is_(None)), 0), func.count().filter(AIGenerationLog.cost_usd.is_(None)))
        .where(AIGenerationLog.created_at >= month_start())).one()
    est = float(reported) + (tin * settings.ai_price_in_per_mtok + tout * settings.ai_price_out_per_mtok) / 1e6
    priced = bool(settings.ai_price_in_per_mtok or settings.ai_price_out_per_mtok)
    return {"calls": calls, "usd": round(est, 4), "unpriced_calls": int(unpriced) if not priced else 0, "tokens_in": int(tin), "tokens_out": int(tout)}


def check_ai_limits() -> dict:
    """The hard limits that actually stop generation (services/ai_usage.py), read from the per-call ledger. Says plainly when none is set or when a USD limit
    cannot be enforced because no per-token price is configured."""
    from app.services import ai_usage

    hard, tok, t_usd, t_tok = settings.ai_platform_hard_limit_usd, settings.ai_platform_monthly_token_limit, settings.ai_tenant_monthly_budget_usd, settings.ai_tenant_monthly_token_budget
    if not (hard > 0 or tok > 0 or t_usd > 0 or t_tok > 0):
        return row("ai_limits", "AI spending limits", "warn", "No platform hard limit and no per-business budget is set: AI calls are recorded but nothing stops them",
                   "Set AI_PLATFORM_HARD_LIMIT_USD (and AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK), and AI_TENANT_MONTHLY_BUDGET_USD for a default per-business budget.")
    if (hard > 0 or t_usd > 0) and not ai_usage.price_known():
        return row("ai_limits", "AI spending limits", "critical", "A USD limit is set but no AI price is configured, so it cannot be measured and generation is blocked (fail closed)",
                   "Set AI_PRICE_IN_PER_MTOK and AI_PRICE_OUT_PER_MTOK from your provider's price list.")
    sp = ai_usage.spend_this_month()
    parts = []
    status = "ok"
    if hard > 0:
        pct = float(sp["usd"]) / hard * 100
        parts.append(f"${float(sp['usd']):.2f} of the ${hard:.2f} platform hard limit ({pct:.0f}%)")
        status = "critical" if pct >= 100 else "warn" if pct >= settings.ai_platform_soft_pct else status
    if tok > 0:
        parts.append(f"{sp['tokens']:,} of {tok:,} platform tokens")
        status = "critical" if sp["tokens"] >= tok else status
    if t_usd > 0 or t_tok > 0:
        parts.append("per-business budget " + " / ".join(x for x in (f"${t_usd:.2f}" if t_usd > 0 else "", f"{t_tok:,} tokens" if t_tok > 0 else "") if x))
    note = f"; {sp['unpriced_calls']} calls have no cost (price not configured)" if sp["unpriced_calls"] and ai_usage.price_known() is False else ""
    return row("ai_limits", "AI spending limits", status, "; ".join(parts) + note,
               "At the soft line only customer review writing keeps running; at 100% everything stops until next month or until the limit is raised." if status != "ok" else "")


def check_ai(db: Session) -> list[dict]:
    out = []
    if not settings.ai_configured:
        out.append(row("ai_provider", "AI provider", "warn", "No AI key configured: drafts and the growth agent are off", "Set GEMINI_API_KEY (or another provider) in the production .env."))
    s = ai_spend(db)
    note = f" ({s['unpriced_calls']} calls report no cost; set AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK)" if s["unpriced_calls"] else ""
    budget = settings.ai_monthly_budget_usd
    if budget <= 0:
        out.append(row("ai_budget", "AI monthly budget", "warn", f"{s['calls']} AI calls this month, about ${s['usd']:.2f} counted{note}. No budget is set",
                       "Set AI_MONTHLY_BUDGET_USD and a billing alert in the provider console."))
    else:
        pct = s["usd"] / budget * 100
        out.append(row("ai_budget", "AI monthly budget", "critical" if pct >= 100 else "warn" if pct >= 80 else "ok",
                       f"${s['usd']:.2f} of ${budget:.2f} used ({pct:.0f}%), {s['calls']} calls{note}",
                       "Raise the budget or reduce usage; also keep a budget alert in the provider console." if pct >= 80 else ""))
    out.append(check_ai_limits())
    day = db.execute(select(func.count(), func.count().filter(AIGenerationLog.status != "ok")).where(AIGenerationLog.created_at >= utcnow() - timedelta(hours=24))).one()
    if day[0] >= 10 and day[1] / day[0] > 0.3:
        out.append(row("ai_errors", "AI errors", "warn", f"{day[1]} of {day[0]} AI calls failed in the last 24 h", "Check the provider key, quota and model name."))
    return out


def check_rank_quota(db: Session) -> dict | None:
    if not (settings.rank_provider and settings.rank_provider_key):
        return None
    used = db.scalar(select(func.count()).select_from(RankCheck).where(RankCheck.checked_at >= month_start())) or 0
    failed = db.scalar(select(func.count()).select_from(RankCheck).where(RankCheck.checked_at >= utcnow() - timedelta(hours=24), RankCheck.status == "error")) or 0
    return row("places", "Places API (local ranking)", "warn" if failed >= 5 else "ok", f"{used} billed searches this month; {failed} failed in 24 h",
               "Failed checks usually mean the key, billing or restrictions." if failed >= 5 else "")


def check_geo_grid(db: Session) -> dict:
    """Geo-grid (maps) spend control. Off is a normal, healthy state. When on, warn at settings.rank_alert_pct of a platform cap and go critical at 100%."""
    from app.services import rank_grid as rg

    guard = rg.platform_guard()
    if guard == "switched_off":
        return row("geo_grid", "Geo-grid maps", "ok", "Switched off (RANK_GRID_ENABLED is false). No map scan can spend Google searches")
    if guard:
        return row("geo_grid", "Geo-grid maps", "critical", f"Switched on but not safe to run: {rg.GUARD_MESSAGES[guard]}", "Set RANK_PLATFORM_DAILY_CAP or RANK_PLATFORM_MONTHLY_CAP and the search price, or switch maps off.")
    parts, worst = [], "ok"
    for label, used, cap in (("today", rg.platform_used_today(db), settings.rank_platform_daily_cap), ("this month", rg.platform_used_this_month(db), settings.rank_platform_monthly_cap)):
        if cap > 0:
            pct = 100 * used / cap
            parts.append(f"{used:,} of {cap:,} searches {label} ({pct:.0f}%)")
            worst = "critical" if pct >= 100 else ("warn" if pct >= settings.rank_alert_pct and worst != "critical" else worst)
    est = f"; about ${rg.platform_used_this_month(db) * settings.rank_cost_per_call_usd:,.2f} this month at the configured price"
    return row("geo_grid", "Geo-grid maps", worst, "On. " + "; ".join(parts) + est, "Raise the cap deliberately or switch maps off (RANK_GRID_ENABLED=false)." if worst != "ok" else "")


def check_subscriptions(db: Session) -> list[dict]:
    now = utcnow()
    past_due = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.status == "past_due")) or 0
    trials = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.status == "trialing", Subscription.trial_ends_at.between(now, now + timedelta(days=3)))) or 0
    lapsed = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.status == "active", Subscription.source == "razorpay",
                                                                           Subscription.current_period_end < now - timedelta(days=2))) or 0
    out = [row("subscriptions", "Subscriptions", "critical" if lapsed else "warn" if past_due else "ok",
               f"{past_due} past due, {trials} trials end within 3 days, {lapsed} paid periods ended without renewal",
               "Lapsed-but-active means a Razorpay webhook was missed: check the webhook delivery log in the Razorpay dashboard." if lapsed else "")]
    razor = bool(settings.razorpay_key_id and settings.razorpay_key_secret and settings.razorpay_webhook_secret)
    out.append(row("razorpay", "Razorpay", "ok" if razor else "warn", "Keys and webhook secret are set" if razor else "Not configured: paid plans cannot be bought",
                   "" if razor else "Add live keys and the webhook secret (Razorpay dashboard, Webhooks, your /api/v1/billing/webhook URL)."))
    return out


def check_google_retention(db: Session) -> dict | None:
    """Only when the Google-content retention job is switched on: it must have run (written its daily audit entry) within 36 hours and without a failed step."""
    if not settings.google_content_retention_enabled:
        return None
    from app.models import AuditLog
    from app.services import google_retention

    last = google_retention.last_run_at(db)
    if last is None or (utcnow() - last).total_seconds() > 36 * 3600:
        return row("google_retention", "Google content retention", "critical", "The retention job has not run in the last 36 hours",
                   "Check the beat and worker containers; expired Google content may still be stored.")
    errors = db.scalar(select(AuditLog.meta).where(AuditLog.action == "retention.google_content_run").order_by(AuditLog.created_at.desc()).limit(1)) or {}
    if errors.get("errors"):
        return row("google_retention", "Google content retention", "critical", f"The last run had failing steps: {', '.join(errors['errors'])}", "See the worker log; the job retries and alerts by email.")
    return row("google_retention", "Google content retention", "ok", f"Last run {last.isoformat(timespec='minutes')}")


def check_backup() -> dict:
    f = settings.backup_status_file
    try:
        present = bool(f) and Path(f).is_file()
    except OSError:  # the folder is not readable by this container: say so instead of failing the whole operations check
        return row("backup", "Database backup", "warn", "The backup status file cannot be read by this container (permissions)", "Mount a status-only folder readable by the application user.")
    if not present:
        return row("backup", "Database backup", "critical" if settings.is_production else "warn", "No backup status found",
                   "Schedule deploy/backup.sh (nightly) and mount ./backups into the api and worker containers.")
    try:
        st = json.loads(Path(f).read_text(encoding="utf-8"))
        at = datetime.fromisoformat(st["finished_at"].replace("Z", "+00:00"))
    except Exception:
        return row("backup", "Database backup", "warn", "Backup status file is unreadable", "Re-run deploy/backup.sh.")
    age_h = (utcnow() - at).total_seconds() / 3600
    problems = []
    if not st.get("ok"):
        problems.append("last run failed: " + str(st.get("error", ""))[:100])
    if not st.get("encrypted"):
        problems.append("not encrypted")
    if not st.get("offsite"):
        problems.append("not copied off the server")
    stale = age_h > settings.backup_max_age_hours
    if stale:
        problems.append(f"last success {age_h:.0f} h ago")
    detail = f"Last backup {age_h:.0f} h ago, {st.get('size_mb', '?')} MB, encrypted={bool(st.get('encrypted'))}, off-site={bool(st.get('offsite'))}"
    if st.get("restore_verified_at"):
        detail += f"; restore last proven {str(st['restore_verified_at'])[:10]}"
    elif not problems:
        problems.append("restore never verified")
    if not problems:
        return row("backup", "Database backup", "ok", detail)
    return row("backup", "Database backup", "critical" if (stale or not st.get("ok")) else "warn", detail + ". " + "; ".join(problems),
               "Run deploy/backup.sh and deploy/verify-restore.sh; see docs/DEPLOYMENT.md.")


def check_monitoring_and_mail() -> list[dict]:
    from app.core import monitoring

    out = [row("sentry", "Error reporting", "ok", "Sentry is receiving errors from the API, worker and scheduler") if monitoring.enabled()
           else row("sentry", "Error reporting", "critical" if settings.is_production else "warn", "No SENTRY_DSN: errors are only in container logs", "Create a Sentry project and set SENTRY_DSN.")]
    out.append(row("smtp", "Email (SMTP)", "ok" if settings.smtp_host else "warn", f"Sending through {settings.smtp_host}" if settings.smtp_host else "SMTP_HOST not set: verification, invitations and resets cannot be delivered",
                   "" if settings.smtp_host else "Set SMTP_* and run `python -m app.cli preflight --smtp-test you@example.com`."))
    probs = config_problems(settings)
    out.append(row("config", "Production configuration", "ok" if not probs else ("critical" if settings.is_production else "warn"),
                   "Passes the production guard" if not probs else f"{len(probs)} problem(s) the production guard would refuse: " + "; ".join(p[:70] for p in probs[:4]),
                   "" if not probs else "Fix these in .env before APP_ENV=production."))
    return out


def run_checks(db: Session) -> dict:
    checks = [check_database(db), check_redis(), check_migrations(db), check_heartbeat(), *check_task_failures(), check_failed_work(db), *check_google_access(db), *check_ai(db)]
    rk = check_rank_quota(db)
    if rk:
        checks.append(rk)
    checks.append(check_geo_grid(db))
    checks += [*check_subscriptions(db), check_backup(), *check_monitoring_and_mail()]
    gr = check_google_retention(db)
    if gr:
        checks.append(gr)
    worst = max((c["status"] for c in checks), key=lambda s: RANK[s])
    return {"status": worst, "checked_at": utcnow().isoformat(), "counts": {s: sum(1 for c in checks if c["status"] == s) for s in RANK}, "checks": checks}


def alert_on_new_critical(result: dict) -> list[str]:
    """Emails FlowHQ admins when a check newly becomes critical (and once a day while it stays so). Returns the ids it alerted about."""
    from app.core import monitoring
    from app.services.mailer import send_email

    r = _redis()
    crit = {c["id"]: c for c in result["checks"] if c["status"] == "critical"}
    if not r:
        return []
    prev = {k.decode(): float(v) for k, v in r.hgetall(ALERT_KEY).items()}
    now = time.time()
    fresh = [i for i in crit if now - prev.get(i, 0) > 86400]
    for gone in set(prev) - set(crit):
        r.hdel(ALERT_KEY, gone)
    if not fresh:
        return []
    body = "FlowQR needs attention:\n\n" + "\n".join(f"- {crit[i]['label']}: {crit[i]['detail']}" + (f"\n  Do this: {crit[i]['action']}" if crit[i]["action"] else "") for i in fresh)
    body += f"\n\nOpen {settings.frontend_url}/admin/ops for the full picture."
    for to in sorted(settings.platform_admin_email_set):
        send_email(to, f"[FlowQR] {len(fresh)} critical issue(s): " + ", ".join(crit[i]["label"] for i in fresh)[:120], body)
    for i in fresh:
        r.hset(ALERT_KEY, i, str(now))
        monitoring.capture_message(f"ops critical: {crit[i]['label']}: {crit[i]['detail']}", "error", check=i)
    return fresh
