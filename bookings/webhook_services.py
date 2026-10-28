import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from bookings.models import Booking, Payment, Hold, ProcessedWebhookEvent


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

    # Never trust event data before checking its signature.
    verify_webhook_signature(
        payload=payload,
        signature=signature,
    )

    if not event_id:
        raise ValidationError("Missing Razorpay event ID.")

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("Invalid webhook JSON payload.") from exc

    event_type = event.get("event")

    if event_type not in ("payment.captured", "payment.failed"):
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
        raise ValidationError("Webhook is missing payment identifiers.")

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
            raise ValidationError("No matching payment order found.")

        booking = Booking.objects.select_for_update().get(
            pk=payment.booking_id
        )

        # The payment lock serializes events for this payment.
        if ProcessedWebhookEvent.objects.filter(
            event_id=event_id
        ).exists():
            return {"detail": "Duplicate event ignored."}

        if event_type == "payment.captured":
            expected_amount = int(payment.amount * 100)

            if amount != expected_amount or currency != "INR":
                raise ValidationError(
                    "Webhook payment amount or currency does not match."
                )

            if payment.status == Payment.Status.FAILED:
                raise ValidationError(
                    "A failed payment cannot be confirmed by this event."
                )

            if payment.status != Payment.Status.SUCCEEDED:
                if booking.status != Booking.Status.PAYMENT_PENDING:
                    raise ValidationError(
                        "Booking is not awaiting payment."
                    )

                payment.provider_payment_id = provider_payment_id
                payment.status = Payment.Status.SUCCEEDED
                payment.save(
                    update_fields=[
                        "provider_payment_id",
                        "status",
                        "updated_at",
                    ]
                )

                booking.status = Booking.Status.CONFIRMED
                booking.save(update_fields=["status", "updated_at"])

                booking.holds.filter(
                    status=Hold.Status.ACTIVE
                ).update(status=Hold.Status.CONVERTED)

            elif payment.provider_payment_id != provider_payment_id:
                raise ValidationError(
                    "A different payment has already succeeded."
                )

        elif event_type == "payment.failed":
            # A delayed failure event must never undo a successful payment.
            if payment.status == Payment.Status.SUCCEEDED:
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

        ProcessedWebhookEvent.objects.create(
            event_id=event_id,
            event_type=event_type,
        )

    return {"detail": "Webhook processed successfully."}