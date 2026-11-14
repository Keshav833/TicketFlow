import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from bookings.email_services import send_booking_confirmation_email
from bookings.models import Booking, BookingEmailDelivery, OutboxEvent, Payment, Ticket
from bookings.outbox import (
    BOOKING_FULFILLMENT_EVENT,
    claim_pending_outbox_events,
    create_booking_fulfillment_outbox,
    mark_outbox_event_completed,
    mark_outbox_event_dispatched,
    mark_outbox_event_failed,
)
from bookings.services import expire_stale_holds
from bookings.ticket_services import generate_tickets

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, retry_backoff=30)
def dispatch_pending_outbox_events(self):
    events = claim_pending_outbox_events(limit=20)
    for event in events:
        try:
            if event.event_type == BOOKING_FULFILLMENT_EVENT:
                fulfill_confirmed_booking.delay(event.id)
            else:
                logger.warning("Unsupported outbox event type: %s", event.event_type)
            mark_outbox_event_dispatched(event)
        except Exception as exc:
            logger.exception("Failed to dispatch outbox event %s", event.id)
            mark_outbox_event_failed(event, error=str(exc), retry_minutes=2)
            raise
    return {"dispatched": len(events)}


@shared_task(bind=True, max_retries=5, retry_backoff=60)
def recover_stale_outbox_events(self):
    threshold = timezone.now() - timedelta(minutes=10)
    rows = OutboxEvent.objects.filter(
        status=OutboxEvent.Status.PROCESSING,
        locked_at__lt=threshold,
    ).update(status=OutboxEvent.Status.PENDING, locked_at=None)
    logger.info("Recovered %s stale outbox events", rows)
    return rows


@shared_task(bind=True, max_retries=6, retry_backoff=60)
def fulfill_confirmed_booking(self, outbox_event_id):
    event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
    booking = Booking.objects.filter(pk=event.aggregate_id).first()

    if booking is None:
        logger.warning("Outbox fulfillment skipped for missing booking %s", event.aggregate_id)
        mark_outbox_event_completed(event, error="booking missing")
        return {"status": "skipped_missing_booking"}

    if booking.status != Booking.Status.CONFIRMED:
        logger.info("Outbox fulfillment skipped for unconfirmed booking %s", booking.id)
        mark_outbox_event_completed(event, error="booking not confirmed")
        return {"status": "skipped_unconfirmed_booking"}

    payment = Payment.objects.filter(
        booking=booking,
        status=Payment.Status.SUCCEEDED,
    ).first()
    if payment is None:
        logger.warning("Outbox fulfillment blocked for booking %s without successful payment", booking.id)
        raise RuntimeError("booking payment not succeeded")

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.id)
        existing_tickets = Ticket.objects.filter(booking_item__booking=booking).count()
        if existing_tickets == 0:
            tickets = generate_tickets(booking.id)
            logger.info("Generated %s tickets for booking %s via outbox", len(tickets), booking.id)
        else:
            logger.info("Ticket generation skipped for booking %s because tickets already exist", booking.id)

    delivery, _ = BookingEmailDelivery.objects.get_or_create(booking=booking)
    if delivery.status == BookingEmailDelivery.Status.SENT:
        logger.info("Email already sent for booking %s", booking.id)
    else:
        send_booking_confirmation_email_task.delay(booking.id)

    mark_outbox_event_completed(event)
    return {"status": "fulfilled", "booking_id": booking.id}


@shared_task(bind=True, max_retries=5, retry_backoff=60)
def send_booking_confirmation_email_task(self, booking_id):
    booking = Booking.objects.select_related("user").filter(pk=booking_id).first()
    if booking is None:
        logger.warning("Email task skipped for missing booking %s", booking_id)
        return {"status": "skipped_missing_booking"}

    delivery, _ = BookingEmailDelivery.objects.get_or_create(booking=booking)
    if delivery.status == BookingEmailDelivery.Status.SENT:
        return {"status": "already_sent", "booking_id": booking_id}

    with transaction.atomic():
        delivery = BookingEmailDelivery.objects.select_for_update().get(pk=delivery.pk)
        if delivery.status == BookingEmailDelivery.Status.SENT:
            return {"status": "already_sent", "booking_id": booking_id}
        delivery.status = BookingEmailDelivery.Status.PROCESSING
        delivery.attempts += 1
        delivery.locked_at = timezone.now()
        delivery.last_error = ""
        delivery.save(update_fields=["status", "attempts", "locked_at", "last_error", "updated_at"])

    try:
        sent = send_booking_confirmation_email(booking_id)
    except Exception as exc:
        logger.exception("Email delivery failed for booking %s", booking_id)
        with transaction.atomic():
            delivery = BookingEmailDelivery.objects.select_for_update().get(pk=delivery.pk)
            delivery.status = BookingEmailDelivery.Status.FAILED
            delivery.last_error = str(exc)
            delivery.locked_at = None
            delivery.save(update_fields=["status", "last_error", "locked_at", "updated_at"])
        raise

    with transaction.atomic():
        delivery = BookingEmailDelivery.objects.select_for_update().get(pk=delivery.pk)
        if sent:
            delivery.status = BookingEmailDelivery.Status.SENT
            delivery.sent_at = timezone.now()
            delivery.locked_at = None
            delivery.last_error = ""
            delivery.save(update_fields=["status", "sent_at", "locked_at", "last_error", "updated_at"])
        else:
            delivery.status = BookingEmailDelivery.Status.FAILED
            delivery.locked_at = None
            delivery.last_error = "email not sent; booking not eligible"
            delivery.save(update_fields=["status", "locked_at", "last_error", "updated_at"])
    return {"status": "sent" if sent else "not_sent", "booking_id": booking_id}


@shared_task(bind=True, max_retries=3, retry_backoff=30)
def recover_stale_email_deliveries(self):
    threshold = timezone.now() - timedelta(minutes=15)
    rows = BookingEmailDelivery.objects.filter(
        status=BookingEmailDelivery.Status.PROCESSING,
        locked_at__lt=threshold,
    ).update(status=BookingEmailDelivery.Status.PENDING, locked_at=None)
    logger.info("Recovered %s stale email deliveries", rows)
    return rows


@shared_task(bind=True, max_retries=5, retry_backoff=60)
def expire_stale_holds_task(self):
    try:
        count = expire_stale_holds()
        logger.info("Expired stale holds count: %s", count)
        return {"expired_holds": count}
    except Exception:
        logger.exception("Failed to expire stale holds")
        raise


@shared_task
def ensure_booking_fulfillment_event(booking):
    create_booking_fulfillment_outbox(booking)
    return {"status": "ok", "booking_id": booking.id}
