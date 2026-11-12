from celery import Celery

from app.core.config import settings

celery_app = Celery("flowqr", broker=settings.redis_url, backend=None, include=["app.workers.tasks"])
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
        "retry-failed-replies": {"task": "flowqr.retry_failed_replies", "schedule": 900.0},
        "purge-review-sessions": {"task": "flowqr.purge_review_sessions", "schedule": 86400.0},
    },
)
