import hashlib
import hmac
import json
import logging

logger = logging.getLogger(__name__)
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError
from bookings.services import reserve_confirmed_seats, transition_booking
from bookings.models import Booking, Payment, Hold, ProcessedWebhookEvent
from bookings.outbox import (
    create_booking_fulfillment_outbox,
    create_late_payment_refund_outbox,
)


def verify_webhook_signature(*, payload, signature):
    """Verify that the raw webhook body was signed with our webhook secret."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    if not secret:
        raise ValidationError("Webhook secret is not configured.")

    if not signature:
        raise ValidationError("Missing webhook signature.")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise ValidationError("Invalid webhook signature.")



def process_razorpay_webhook(*, payload, signature, event_id):
    """Verify and process supported Razorpay webhook events."""

    logger.info("Razorpay webhook received")

    # Never trust event data before checking its signature.
    try:
        verify_webhook_signature(
            payload=payload,
            signature=signature,
        )
    except Exception:
        logger.exception("Razorpay webhook signature verification failed")
        raise

    logger.info("Razorpay webhook signature verified")

    if not event_id:
        logger.warning("Webhook rejected: missing event ID")
        raise ValidationError("Missing Razorpay event ID.")

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Webhook rejected: invalid JSON payload")
        raise ValidationError(
            "Invalid webhook JSON payload."
        ) from exc

    event_type = event.get("event")

    logger.info(
        "Processing Razorpay webhook event: %s",
        event_type,
    )

    if event_type not in ("payment.captured", "payment.failed"):
        logger.info(
            "Unsupported webhook event ignored: %s",
            event_type,
        )
        return {"detail": "Event ignored.", "event": event_type}

    payment_entity = (
        event.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    order_id = payment_entity.get("order_id")
    provider_payment_id = payment_entity.get("id")
    amount = payment_entity.get("amount")
    currency = payment_entity.get("currency")

    if not order_id or not provider_payment_id:
        logger.warning(
            "Webhook rejected: missing payment identifiers"
        )
        raise ValidationError(
            "Webhook is missing payment identifiers."
        )

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .filter(
                provider="razorpay",
                provider_order_id=order_id,
            )
            .first()
        )

        if payment is None:
            logger.warning(
                "Webhook rejected: no matching payment order found"
            )
            raise ValidationError(
                "No matching payment order found."
            )

        booking = Booking.objects.select_for_update().get(
            pk=payment.booking_id
        )

        # The payment lock serializes events for this payment.
        if ProcessedWebhookEvent.objects.filter(
            event_id=event_id
        ).exists():
            logger.info(
                "Duplicate webhook event ignored: %s",
                event_id,
            )
            return {"detail": "Duplicate event ignored."}

        if event_type == "payment.captured":
            expected_amount = int(payment.amount * 100)

            if amount != expected_amount or currency != "INR":
                logger.warning(
                    "Webhook payment amount or currency mismatch "
                    "for booking %s",
                    booking.id,
                )
                raise ValidationError(
                    "Webhook payment amount or currency does not match."
                )

            if booking.status in {Booking.Status.EXPIRED, Booking.Status.CANCELLED}:
                if payment.status not in {
                    Payment.Status.PENDING,
                    Payment.Status.REFUND_PENDING,
                    Payment.Status.REFUNDED,
                }:
                    raise ValidationError(
                        "Expired booking payment cannot be reconciled."
                    )
                if (
                    payment.provider_payment_id
                    and payment.provider_payment_id != provider_payment_id
                ):
                    raise ValidationError(
                        "A different payment has already been recorded."
                    )
                if payment.status == Payment.Status.PENDING:
                    payment.provider_payment_id = provider_payment_id
                    payment.status = Payment.Status.REFUND_PENDING
                    payment.save(
                        update_fields=[
                            "provider_payment_id",
                            "status",
                            "updated_at",
                        ]
                    )
                    create_late_payment_refund_outbox(payment)

                ProcessedWebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type,
                )
                logger.warning(
                    "Queued refund for late captured payment on expired booking %s",
                    booking.id,
                )
                return {"detail": "Late payment queued for refund."}

            if payment.status == Payment.Status.FAILED:
                logger.warning(
                    "Captured event rejected for previously failed "
                    "payment %s",
                    payment.id,
                )
                raise ValidationError(
                    "A failed payment cannot be confirmed by this event."
                )

            if payment.status != Payment.Status.SUCCEEDED:
                if booking.status != Booking.Status.PAYMENT_PENDING:
                    logger.warning(
                        "Captured event rejected: booking %s "
                        "is not awaiting payment",
                        booking.id,
                    )
                    raise ValidationError(
                        "Booking is not awaiting payment."
                    )

                reserve_confirmed_seats(booking=booking)

                payment.provider_payment_id = provider_payment_id
                payment.status = Payment.Status.SUCCEEDED

                payment.save(
                    update_fields=[
                        "provider_payment_id",
                        "status",
                        "updated_at",
                    ]
                )

                transition_booking(
                    booking=booking,
                    new_status=Booking.Status.CONFIRMED,
                )

                booking.holds.filter(
                    status=Hold.Status.ACTIVE
                ).update(status=Hold.Status.CONVERTED)

                create_booking_fulfillment_outbox(booking)

                logger.info(
                    "Payment captured and booking %s confirmed",
                    booking.id,
                )

            elif payment.provider_payment_id != provider_payment_id:
                logger.warning(
                    "Different successful payment detected "
                    "for booking %s",
                    booking.id,
                )
                raise ValidationError(
                    "A different payment has already succeeded."
                )

            logger.info(
                "Payment captured for booking %s; fulfillment will be handled asynchronously via outbox.",
                booking.id,
            )

        elif event_type == "payment.failed":
            # A delayed failure event must never undo a successful payment.
            if payment.status == Payment.Status.SUCCEEDED:
                logger.warning(
                    "Delayed payment failure ignored for successful "
                    "booking %s",
                    booking.id,
                )

                ProcessedWebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type,
                )

                return {
                    "detail": "Failure event ignored for successful payment."
                }

            if payment.status == Payment.Status.PENDING:
                payment.provider_payment_id = provider_payment_id
                payment.status = Payment.Status.FAILED

                payment.save(
                    update_fields=[
                        "provider_payment_id",
                        "status",
                        "updated_at",
                    ]
                )

                logger.warning(
                    "Payment failed for booking %s",
                    booking.id,
                )

        ProcessedWebhookEvent.objects.create(
            event_id=event_id,
            event_type=event_type,
        )

    logger.info(
        "Razorpay webhook processed successfully: event=%s, event_id=%s",
        event_type,
        event_id,
    )

    return {"detail": "Webhook processed successfully."}
