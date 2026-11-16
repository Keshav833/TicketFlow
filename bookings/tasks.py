import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from bookings.email_services import send_booking_confirmation_email
from bookings.models import Booking, BookingEmailDelivery, OutboxEvent, Payment
from bookings.outbox import (
    BOOKING_REFUND_EVENT,
    BOOKING_FULFILLMENT_EVENT,
    LATE_PAYMENT_REFUND_EVENT,
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
                mark_outbox_event_dispatched(event)
                fulfill_confirmed_booking.delay(event.id)
            elif event.event_type in {LATE_PAYMENT_REFUND_EVENT, BOOKING_REFUND_EVENT}:
                mark_outbox_event_dispatched(event)
                refund_late_payment.delay(event.id)
            else:
                logger.warning("Unsupported outbox event type: %s", event.event_type)
                mark_outbox_event_completed(event, error="unsupported event type")
        except Exception as exc:
            logger.exception("Failed to dispatch outbox event %s", event.id)
            mark_outbox_event_failed(event, error=str(exc), retry_minutes=2)
            raise
    return {"dispatched": len(events)}


@shared_task(bind=True, max_retries=5, retry_backoff=60)
def recover_stale_outbox_events(self):
    threshold = timezone.now() - timedelta(minutes=10)
    rows = OutboxEvent.objects.filter(
        status__in=[OutboxEvent.Status.PROCESSING, OutboxEvent.Status.DISPATCHED],
        locked_at__lt=threshold,
    ).update(status=OutboxEvent.Status.PENDING, locked_at=None)
    logger.info("Recovered %s stale outbox events", rows)
    return rows


@shared_task(bind=True, max_retries=6, retry_backoff=60)
def fulfill_confirmed_booking(self, outbox_event_id):
    event = None
    try:
        with transaction.atomic():
            event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
            if event.status == OutboxEvent.Status.COMPLETED:
                return {"status": "already_completed"}
            if event.status == OutboxEvent.Status.PROCESSING:
                threshold = timezone.now() - timedelta(minutes=10)
                if event.locked_at and event.locked_at >= threshold:
                    return {"status": "already_processing"}

            event.status = OutboxEvent.Status.PROCESSING
            event.locked_at = timezone.now()
            event.save(update_fields=["status", "locked_at", "updated_at"])

            booking = Booking.objects.filter(pk=event.aggregate_id).first()
            if booking is None:
                logger.warning(
                    "Outbox fulfillment skipped for missing booking %s",
                    event.aggregate_id,
                )
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
                raise RuntimeError("booking payment not succeeded")

            booking = Booking.objects.select_for_update().get(pk=booking.id)
            tickets = generate_tickets(booking.id)
            logger.info("Generated %s tickets for booking %s via outbox", len(tickets), booking.id)

            delivery, _ = BookingEmailDelivery.objects.get_or_create(booking=booking)

        if delivery.status == BookingEmailDelivery.Status.SENT:
            logger.info("Email already sent for booking %s", booking.id)
        else:
            send_booking_confirmation_email_task.delay(booking.id)

        mark_outbox_event_completed(event)
        return {"status": "fulfilled", "booking_id": booking.id}
    except Exception as exc:
        logger.exception("Fulfillment failed for outbox event %s", outbox_event_id)
        if event is not None:
            event = OutboxEvent.objects.get(pk=outbox_event_id)
            mark_outbox_event_failed(event, error=str(exc), retry_minutes=2)
        raise


@shared_task(bind=True, max_retries=6, retry_backoff=60)
def refund_late_payment(self, outbox_event_id):
    """Refund a captured payment whose booking expired before confirmation."""
    event = None
    try:
        with transaction.atomic():
            event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
            if event.status == OutboxEvent.Status.COMPLETED:
                return {"status": "already_completed"}

            payment = Payment.objects.select_for_update().get(pk=event.aggregate_id)
            if payment.status == Payment.Status.REFUNDED:
                mark_outbox_event_completed(event)
                return {"status": "already_refunded", "payment_id": payment.id}
            if payment.status != Payment.Status.REFUND_PENDING:
                mark_outbox_event_completed(event, error="payment not awaiting refund")
                return {"status": "skipped", "payment_id": payment.id}
            if not payment.provider_payment_id:
                raise RuntimeError("late payment is missing its provider payment ID")

            payment_id = payment.id
            provider_payment_id = payment.provider_payment_id
            amount = int(payment.amount * 100)

        from bookings.payment_services import get_razorpay_client

        refund = get_razorpay_client().payment.refund(
            provider_payment_id,
            {
                "amount": amount,
                "notes": {"reason": "booking_hold_expired"},
            },
        )

        with transaction.atomic():
            event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
            payment = Payment.objects.select_for_update().select_related("booking").get(pk=payment_id)
            if payment.status == Payment.Status.REFUNDED:
                mark_outbox_event_completed(event)
                return {"status": "already_refunded", "payment_id": payment.id}

            payment.provider_refund_id = refund.get("id", "")
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=["provider_refund_id", "status", "updated_at"])
            booking = payment.booking
            if booking.status == Booking.Status.REFUND_PENDING:
                from bookings.services import transition_booking
                from bookings.models import Ticket

                transition_booking(
                    booking=booking,
                    new_status=Booking.Status.REFUNDED,
                )
                Ticket.objects.filter(
                    booking_item__booking=booking,
                    status=Ticket.Status.ISSUED,
                ).update(status=Ticket.Status.CANCELLED)
            mark_outbox_event_completed(event)
        logger.warning("Refunded late payment %s", payment_id)
        return {"status": "refunded", "payment_id": payment_id}
    except Exception as exc:
        logger.exception("Late-payment refund failed for outbox event %s", outbox_event_id)
        if event is not None:
            event = OutboxEvent.objects.get(pk=outbox_event_id)
            mark_outbox_event_failed(event, error=str(exc), retry_minutes=2)
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
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
        if (
            delivery.status == BookingEmailDelivery.Status.PROCESSING
            and delivery.locked_at
            and delivery.locked_at >= timezone.now() - timedelta(minutes=15)
        ):
            return {"status": "already_processing", "booking_id": booking_id}
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
    with transaction.atomic():
        stale_booking_ids = list(
            BookingEmailDelivery.objects.select_for_update(skip_locked=True)
            .filter(
                status=BookingEmailDelivery.Status.PROCESSING,
                locked_at__lt=threshold,
            )
            .values_list("booking_id", flat=True)
        )
        if stale_booking_ids:
            BookingEmailDelivery.objects.filter(
                booking_id__in=stale_booking_ids,
            ).update(status=BookingEmailDelivery.Status.PENDING, locked_at=None)

        pending_booking_ids = list(
            BookingEmailDelivery.objects.filter(
                status=BookingEmailDelivery.Status.PENDING,
            )
            .order_by("updated_at")
            .values_list("booking_id", flat=True)[:100]
        )

    booking_ids = list(dict.fromkeys(stale_booking_ids + pending_booking_ids))
    for booking_id in booking_ids:
        send_booking_confirmation_email_task.delay(booking_id)

    logger.info("Queued %s pending email deliveries", len(booking_ids))
    return {"queued": len(booking_ids), "recovered": len(stale_booking_ids)}


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
