"""Worker and scheduler self-monitoring: Celery signals record every job's outcome (for the ops dashboard and failed-job alerts), start
error reporting inside the worker and beat processes, and a one-minute heartbeat proves that beat schedules AND a worker executes."""
from celery.signals import beat_init, celeryd_init, task_failure, task_success

from app.core import monitoring
from app.services import ops
from app.workers.celery_app import celery_app

SKIP = {"flowqr.heartbeat"}


@celeryd_init.connect
def _worker_start(**_):
    monitoring.init("worker")


@beat_init.connect
def _beat_start(**_):
    monitoring.init("beat")


@task_success.connect
def _ok(sender=None, **_):
    if sender and sender.name not in SKIP:
        ops.record_task(sender.name, True)


@task_failure.connect
def _fail(sender=None, exception=None, **_):
    if sender and sender.name not in SKIP:
        ops.record_task(sender.name, False, type(exception).__name__ if exception else "error")


@celery_app.task(name="flowqr.heartbeat")
def heartbeat():
    ops.record_heartbeat()
    return "ok"


@celery_app.task(name="flowqr.ops_watch")
def ops_watch():
    """Every 15 minutes: run the platform checks and email FlowHQ admins when something newly turns critical."""
    from app.core.db import system_session

    db = system_session()
    try:
        result = ops.run_checks(db)
    finally:
        db.close()
    alerted = ops.alert_on_new_critical(result)
    return {"status": result["status"], "alerted": alerted}
