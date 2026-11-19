import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "dispatch-pending-outbox-events": {
        "task": "bookings.tasks.dispatch_pending_outbox_events",
        "schedule": 30.0,
    },
    "recover-stale-outbox-events": {
        "task": "bookings.tasks.recover_stale_outbox_events",
        "schedule": 120.0,
    },
    "expire-stale-holds": {
        "task": "bookings.tasks.expire_stale_holds_task",
        "schedule": 60.0,
    },
    "recover-stale-email-deliveries": {
        "task": "bookings.tasks.recover_stale_email_deliveries",
        "schedule": 300.0,
    },
    "reconcile-submitted-refunds": {
        "task": "bookings.tasks.reconcile_submitted_refunds",
        "schedule": 300.0,
    },
    "reconcile-uncertain-payments": {
        "task": "bookings.tasks.reconcile_uncertain_payments",
        "schedule": 300.0,
    },
}

app.conf.task_default_queue = "default"
app.conf.worker_pool = "solo"
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.result_expires = 3600
