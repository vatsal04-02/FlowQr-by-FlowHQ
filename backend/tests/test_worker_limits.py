"""Every background task has a time limit, so one hung network call can never hold a worker slot for ever, and worker processes are recycled."""
from app.workers.celery_app import celery_app


def test_tasks_have_a_soft_and_a_hard_time_limit_and_workers_are_recycled():
    c = celery_app.conf
    assert 0 < c.task_soft_time_limit < c.task_time_limit, "a soft limit (cleanup chance) must come before the hard kill"
    assert c.task_time_limit <= 3600
    assert 0 < c.worker_max_tasks_per_child <= 1000
    assert c.task_acks_late and c.worker_prefetch_multiplier == 1  # unchanged: a crashed task is picked up again, and one worker does not hoard tasks


def test_no_task_sets_its_own_limit_above_the_global_hard_limit():
    from app.workers import tasks  # noqa: F401  (imports register every task)
    hard = celery_app.conf.task_time_limit
    for name, t in celery_app.tasks.items():
        if name.startswith("flowqr."):
            assert (t.time_limit or 0) <= hard, f"{name} overrides the hard limit"
