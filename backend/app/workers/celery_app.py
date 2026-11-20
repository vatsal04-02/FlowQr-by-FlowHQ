from celery import Celery

from app.core.config import settings

celery_app = Celery("flowqr", broker=settings.redis_url, backend=None, include=["app.workers.tasks", "app.workers.monitor"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    timezone="UTC",
    beat_schedule={
        "sync-due-google-locations": {
            "task": "flowqr.sync_due_locations",
            "schedule": settings.review_sync_interval_minutes * 60 / 2,  # check twice per interval
        },
        "billing-housekeeping": {"task": "flowqr.billing_refresh", "schedule": 3600.0},
        "whatsapp-run-due": {"task": "flowqr.whatsapp_run_due", "schedule": 60.0},  # automations and campaigns due now (does nothing unless sending is enabled and not stopped)
        "whatsapp-conversations-due": {"task": "flowqr.whatsapp_conversations_due", "schedule": 30.0},  # safety net for the short wait before a conversation is looked at (no-op unless WHATSAPP_CONVERSATIONS_ENABLED)
        "whatsapp-booking-reminders": {"task": "flowqr.whatsapp_booking_reminders", "schedule": 300.0},  # appointment reminders due now (no-op unless WHATSAPP_BOOKING_ENABLED; sends only if sending is on)
        "whatsapp-housekeeping": {"task": "flowqr.whatsapp_housekeeping", "schedule": 600.0},  # no-op unless WHATSAPP_ENABLED (services/whatsapp)
        "sites-housekeeping": {"task": "flowqr.sites_housekeeping", "schedule": 3600.0},  # no-op unless SITES_ENABLED (services/sites/service.py)
        "prepaid-reconcile": {"task": "flowqr.prepaid_reconcile", "schedule": 3600.0},  # prepaid plans: catches a lost webhook or a closed tab after paying
        "billing-reconcile": {"task": "flowqr.billing_reconcile", "schedule": 3600.0},  # Cashfree: the safety net for webhooks that never arrive
        "retry-failed-replies": {"task": "flowqr.retry_failed_replies", "schedule": 900.0},
        "auto-replies": {"task": "flowqr.auto_replies", "schedule": 300.0},  # template replies to new positive reviews (services/auto_reply.py)
        "publish-due-posts": {"task": "flowqr.publish_due_posts", "schedule": 60.0},
        "publish-due-media": {"task": "flowqr.publish_due_media", "schedule": 60.0},
        "recover-stuck-posts": {"task": "flowqr.recover_stuck_posts", "schedule": 300.0},
        "autonomy-execute": {"task": "flowqr.autonomy_execute", "schedule": 120.0},
        "autonomy-housekeeping": {"task": "flowqr.autonomy_housekeeping", "schedule": 300.0},
        "autonomy-followups": {"task": "flowqr.autonomy_followups", "schedule": 3600.0},
        "autonomy-retention": {"task": "flowqr.autonomy_retention", "schedule": 86400.0},
        "privacy-retention": {"task": "flowqr.privacy_retention", "schedule": 86400.0},  # does nothing unless PRIVACY_RETENTION_ENABLED=true
        "autonomy-scan": {"task": "flowqr.autonomy_scan", "schedule": 21600.0},
        "daily-agent": {"task": "flowqr.daily_agent", "schedule": 1800.0},
        "purge-deleted-accounts": {"task": "flowqr.purge_deleted_accounts", "schedule": 3600.0},
        "purge-review-sessions": {"task": "flowqr.purge_review_sessions", "schedule": 86400.0},
        "check-ranks": {"task": "flowqr.check_ranks", "schedule": 21600.0},
        "check-rank-grids": {"task": "flowqr.check_rank_grids", "schedule": 21600.0},
        "heartbeat": {"task": "flowqr.heartbeat", "schedule": 60.0},
        "ops-watch": {"task": "flowqr.ops_watch", "schedule": 900.0},
        "notify-by-email": {"task": "flowqr.notify_by_email", "schedule": 3600.0},
    },
)
