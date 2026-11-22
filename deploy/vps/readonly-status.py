"""READ-ONLY inspection of a running FlowQR stack, run INSIDE the api container:

    ssh <deploy user>@<server> "docker exec -i flowqr-production-api-1 python -" < deploy/vps/readonly-status.py

Use it before a release (the starting state), right after it (the same output, compared) and any time you want the Admin > Operations picture without the browser. It prints booleans, counts and statuses only: never a secret, a token, an address or customer text.
It does not import app.main (so it neither runs the startup guard nor initialises error reporting) and writes nothing."""
import json
import time

from sqlalchemy import func, select, text

from app.core.config import settings as s

print("== flags (booleans / non-secret enums only)")
flags = {
    "app_env": s.app_env, "hardened": s.hardened, "cookie_secure": s.cookie_secure, "require_verified_email": s.require_verified_email, "registration_mode": s.effective_registration_mode,
    "sentry_dsn_set": bool(s.sentry_dsn), "sentry_environment": s.sentry_environment or "(defaults to app_env)", "sentry_traces_sample_rate": s.sentry_traces_sample_rate,
    "smtp_host_set": bool(s.smtp_host), "smtp_user_set": bool(s.smtp_user), "smtp_starttls": s.smtp_starttls, "smtp_host_is_local_sink": (s.smtp_host or "").lower() in ("localhost", "127.0.0.1", "mailpit", "mailhog"),
    "platform_admin_emails_count": len(s.platform_admin_email_set),
    "google_configured": s.google_configured, "google_login_configured": s.google_login_configured,
    "agency_manager": s.google_agency_manager_enabled, "agency_operations": s.google_agency_operations_enabled, "agency_internal_only": s.google_agency_internal_only,
    "agency_operator_count": len(s.google_agency_operator_set), "agency_policy_reference_set": bool(s.google_agency_policy_reference.strip()),
    "agency_internal_decision_set": bool(s.google_agency_internal_decision.strip()), "agency_adopt_existing": s.google_agency_adopt_existing_access,
    "agency_individual_fallback": s.google_agency_individual_fallback, "agency_client_token_keep_hours": s.google_agency_client_token_keep_hours,
    "google_content_retention_enabled": s.google_content_retention_enabled, "google_content_retention_days": s.google_content_retention_days,
    "billing_provider": s.billing_provider, "cashfree_enabled": s.cashfree_enabled, "cashfree_env": s.cashfree_env, "prepaid_checkout_enabled": s.prepaid_checkout_enabled,
    "ai_configured": s.ai_configured, "ai_provider": s.ai_provider, "review_sync_interval_minutes": s.review_sync_interval_minutes,
    "whatsapp_enabled": s.whatsapp_enabled, "sites_enabled": s.sites_enabled,
    "autonomy_emergency_stop_env": getattr(s, "autonomy_emergency_stop", None),
}
for k, v in flags.items():
    print(f"  {k} = {v}")

print("== backup status file (ok / encrypted / offsite only)")
try:
    b = json.load(open(s.backup_status_file))
    print("  ", {k: b.get(k) for k in ("ok", "encrypted", "offsite", "finished_at", "offsite_verified_at", "restore_verified_at", "size_mb")})
except Exception as exc:  # noqa: BLE001
    print("   cannot read:", type(exc).__name__)

from app.core.db import system_session  # noqa: E402
from app.models import GoogleAgencyAuthorization, GoogleAgencyTenantGrant, GoogleConnection, GoogleLocation, Tenant, User  # noqa: E402
from app.services import ops  # noqa: E402

db = system_session()
try:
    db.execute(text("SET TRANSACTION READ ONLY"))
    print("== database (counts only)")
    print("   alembic:", [r[0] for r in db.execute(text("SELECT version_num FROM alembic_version"))])
    print("   tenants:", db.scalar(select(func.count()).select_from(Tenant)), " users:", db.scalar(select(func.count()).select_from(User)))
    print("   google connections by status/mode:", [(str(a), m, n) for a, m, n in db.execute(select(GoogleConnection.status, GoogleConnection.auth_mode, func.count()).group_by(GoogleConnection.status, GoogleConnection.auth_mode))])
    rows = db.execute(select(GoogleLocation.last_sync_status, func.count(), func.max(GoogleLocation.last_synced_at), func.max(GoogleLocation.consecutive_failures)).where(GoogleLocation.selected.is_(True)).group_by(GoogleLocation.last_sync_status)).all()
    print("   selected locations by sync status (status, count, newest sync, max consecutive failures):", [(a, n, str(t)[:19] if t else None, f) for a, n, t, f in rows])
    stuck = db.scalar(text("SELECT count(*) FROM google_locations WHERE last_sync_status='running' AND updated_at < now() - interval '30 minutes'"))
    print("   locations stuck on 'running' > 30 min (the F-01 symptom):", stuck)
    print("   agency authorizations:", db.scalar(select(func.count()).select_from(GoogleAgencyAuthorization)), " open tenant grants:", db.scalar(text("SELECT count(*) FROM google_agency_tenant_grants WHERE revoked_at IS NULL")))
    print("   operator addresses registered as users:", db.scalar(select(func.count()).select_from(User).where(func.lower(User.email).in_(list(s.google_agency_operator_set) or ["-"]))))
    print("   scheduled posts overdue > 1 h, by tenant count:", db.scalar(text("SELECT count(DISTINCT tenant_id) FROM scheduled_posts WHERE status='scheduled' AND scheduled_for < now() - interval '1 hour'")))
    print("== the Operations checks (the same data as Admin > Operations; label, status, first 140 chars of detail)")
    res = ops.run_checks(db)
    print("   overall:", res["status"], res["counts"])
    for c in res["checks"]:
        print(f"   [{c['status']:8}] {c['label']}: {str(c['detail'])[:140]}")
    r = ops._redis()
    hb = r.get(ops.HEARTBEAT_KEY) if r else None
    print("== heartbeat age (s):", round(time.time() - float(hb)) if hb else None)
    jobs = {k.decode(): json.loads(v) for k, v in (r.hgetall(ops.TASKS_KEY).items() if r else [])}
    print("== job outcomes recorded by the worker (name: last ok age s, last failure age s, failures total)")
    now = time.time()
    for n, d in sorted(jobs.items()):
        print(f"   {n}: ok {round(now - d['ok_at']) if d.get('ok_at') else None}s, fail {round(now - d['fail_at']) if d.get('fail_at') else None}s, fails {d.get('fails', 0)}")
finally:
    db.close()
