from celery import shared_task


@shared_task
def core_heartbeat():
    return "core heartbeat ok"