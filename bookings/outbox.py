from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bookings.models import OutboxEvent


BOOKING_FULFILLMENT_EVENT = "booking_fulfillment"
LATE_PAYMENT_REFUND_EVENT = "late_payment_refund"
BOOKING_REFUND_EVENT = "booking_refund"


def create_booking_fulfillment_outbox(booking):
    """Create a durable fulfillment event tied to the booking confirmation."""
    key = f"booking_fulfillment:{booking.id}"
    event, created = OutboxEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "event_type": BOOKING_FULFILLMENT_EVENT,
            "aggregate_id": booking.id,
            "status": OutboxEvent.Status.PENDING,
            "payload": {"booking_id": booking.id},
            "available_at": timezone.now(),
        },
    )
    if not created and event.status in {OutboxEvent.Status.COMPLETED, OutboxEvent.Status.DISPATCHED}:
        return event
    if not created and event.status == OutboxEvent.Status.PENDING:
        event.payload = {"booking_id": booking.id}
        event.available_at = timezone.now()
        event.last_error = ""
        event.save(update_fields=["payload", "available_at", "last_error", "updated_at"])

    if settings.CELERY_TASK_ALWAYS_EAGER:
        from bookings.tasks import dispatch_pending_outbox_events

        transaction.on_commit(lambda: dispatch_pending_outbox_events.delay())

    return event


def create_late_payment_refund_outbox(payment):
    """Queue exactly one refund for a capture received after hold expiry."""
    key = f"late_payment_refund:{payment.id}"
    event, created = OutboxEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "event_type": LATE_PAYMENT_REFUND_EVENT,
            "aggregate_id": payment.id,
            "status": OutboxEvent.Status.PENDING,
            "payload": {"payment_id": payment.id},
            "available_at": timezone.now(),
        },
    )
    if not created and event.status == OutboxEvent.Status.PENDING:
        event.available_at = timezone.now()
        event.last_error = ""
        event.save(update_fields=["available_at", "last_error", "updated_at"])

    if settings.CELERY_TASK_ALWAYS_EAGER:
        from bookings.tasks import dispatch_pending_outbox_events

        transaction.on_commit(lambda: dispatch_pending_outbox_events.delay())

    return event


def create_booking_refund_outbox(payment):
    key = f"booking_refund:{payment.id}"
    event, _ = OutboxEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "event_type": BOOKING_REFUND_EVENT,
            "aggregate_id": payment.id,
            "status": OutboxEvent.Status.PENDING,
            "payload": {"payment_id": payment.id},
            "available_at": timezone.now(),
        },
    )
    if settings.CELERY_TASK_ALWAYS_EAGER:
        from bookings.tasks import dispatch_pending_outbox_events

        transaction.on_commit(lambda: dispatch_pending_outbox_events.delay())
    return event


@transaction.atomic
def claim_pending_outbox_events(limit=20):
    now = timezone.now()
    events = list(
        OutboxEvent.objects.select_for_update(skip_locked=True)
        .filter(
            status__in=[OutboxEvent.Status.PENDING, OutboxEvent.Status.FAILED],
            available_at__lte=now,
        )
        .order_by("created_at")[:limit]
    )

    for event in events:
        event.status = OutboxEvent.Status.PROCESSING
        event.locked_at = now
        event.attempts += 1
        event.last_error = ""
        event.save(update_fields=["status", "locked_at", "attempts", "last_error", "updated_at"])

    return events


def mark_outbox_event_dispatched(event):
    event.status = OutboxEvent.Status.DISPATCHED
    event.dispatched_at = timezone.now()
    event.locked_at = event.dispatched_at
    event.save(update_fields=["status", "dispatched_at", "locked_at", "updated_at"])


def mark_outbox_event_completed(event, *, error=None):
    event.status = OutboxEvent.Status.COMPLETED
    event.processed_at = timezone.now()
    event.locked_at = None
    event.last_error = error or ""
    event.save(update_fields=["status", "processed_at", "locked_at", "last_error", "updated_at"])


def mark_outbox_event_failed(event, *, error, retry_minutes=5):
    event.status = OutboxEvent.Status.FAILED
    event.last_error = error[:5000]
    event.available_at = timezone.now() + timedelta(minutes=retry_minutes)
    event.locked_at = None
    event.save(update_fields=["status", "last_error", "available_at", "locked_at", "updated_at"])
