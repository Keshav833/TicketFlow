
from decimal import Decimal

import logging

logger = logging.getLogger(__name__)
import razorpay
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from bookings.services import transition_booking

from bookings.models import Booking, Payment, Hold
from bookings.outbox import create_booking_fulfillment_outbox
from bookings.services import start_booking_payment



def get_razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise RuntimeError("Razorpay credentials are not configured.")

    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def format_payment_response(booking, payment):
    amount_paise = int(
        (payment.amount * Decimal("100")).quantize(Decimal("1"))
    )

    return {
        "booking_id": booking.id,
        "payment_id": payment.id,
        "razorpay_order_id": payment.provider_order_id,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "amount": amount_paise,
        "currency": "INR",
    }


def create_razorpay_order(*, user, booking_id):
    # Check ownership and look for an order we can safely reuse.
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .filter(id=booking_id, user=user)
            .first()
        )

        if booking is None:
            raise ValidationError("Booking not found.")

        existing_payment = (
            Payment.objects.filter(
                booking=booking,
                provider="razorpay",
            )
            .order_by("-id")
            .first()
        )

        if existing_payment and existing_payment.provider_order_id:
            if existing_payment.status == Payment.Status.PENDING:
                return format_payment_response(booking, existing_payment)

            raise ValidationError(
                "This payment is not available for checkout."
            )

        if existing_payment:
            if existing_payment.status == Payment.Status.CREATING:
                raise ValidationError(
                    "Payment order creation is already in progress or "
                    "its outcome is uncertain. Reconciliation is required "
                    "before retrying."
                )

            raise ValidationError(
                "An existing payment requires reconciliation before retrying."
            )

    # Validate the booking and move it to payment_pending.
    booking = start_booking_payment(
        user=user,
        booking_id=booking_id,
    )

    amount_paise = int(
        (booking.total_amount * Decimal("100")).quantize(Decimal("1"))
    )

    if amount_paise <= 0:
        raise ValidationError("Booking amount must be greater than zero.")

    # Create a durable local record before calling the provider.
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(id=booking.id)

        # Recheck after acquiring the lock, in case another request won.
        existing_payment = (
            Payment.objects.filter(
                booking=booking,
                provider="razorpay",
            )
            .order_by("-id")
            .first()
        )

        if existing_payment:
            if (
                existing_payment.provider_order_id
                and existing_payment.status == Payment.Status.PENDING
            ):
                return format_payment_response(booking, existing_payment)

            raise ValidationError(
                "A payment attempt already exists. Reconciliation is required."
            )

        payment = Payment.objects.create(
            booking=booking,
            provider="razorpay",
            provider_order_id="",
            provider_payment_id="",
            idempotency_key=f"booking_{booking.id}_razorpay",
            status=Payment.Status.CREATING,
            amount=booking.total_amount,
        )

    # Do not automatically repeat this remote call after an exception:
    # Razorpay may have created the order even if the response was lost.
    try:
        client = get_razorpay_client()
        order = client.order.create(
            data={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"booking_{booking.id}",
                "notes": {
                    "booking_id": str(booking.id),
                    "user_id": str(user.id),
                },
            }
        )
    except Exception as exc:
        raise ValidationError(
            "Payment order creation could not be confirmed. "
            "The payment attempt needs reconciliation before retrying."
        ) from exc

    # Persist the provider order and transition to pending.
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(id=payment.id)

        payment.provider_order_id = order["id"]
        payment.status = Payment.Status.PENDING
        payment.save(
            update_fields=["provider_order_id", "status"]
        )

    return format_payment_response(booking, payment)


def verify_razorpay_payment(
    *,
    user,
    booking_id,
    razorpay_order_id,
    razorpay_payment_id,
    razorpay_signature,
):
    from django.db import transaction
    from rest_framework.exceptions import ValidationError

    logger.info(
        "Payment verification started for booking %s",
        booking_id,
    )

    # First transaction: validate booking and payment state.
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .filter(id=booking_id, user=user)
            .first()
        )

        if booking is None:
            logger.warning(
                "Payment verification rejected: booking %s not found",
                booking_id,
            )
            raise ValidationError("Booking not found.")

        payment = (
            Payment.objects.select_for_update()
            .filter(
                booking=booking,
                provider="razorpay",
                provider_order_id=razorpay_order_id,
            )
            .first()
        )

        if payment is None:
            logger.warning(
                "Payment order mismatch for booking %s",
                booking.id,
            )
            raise ValidationError(
                "Payment order does not match this booking."
            )

        if payment.status == Payment.Status.SUCCEEDED:
            if payment.provider_payment_id == razorpay_payment_id:
                logger.info(
                    "Duplicate payment verification for booking %s",
                    booking.id,
                )
                return {
                    "detail": "Payment already verified.",
                    "booking_id": booking.id,
                    "payment_id": payment.id,
                    "payment_status": payment.status,
                    "booking_status": booking.status,
                }

            logger.warning(
                "Different successful payment detected for booking %s",
                booking.id,
            )
            raise ValidationError(
                "Booking already has a different successful payment."
            )

        if payment.status != Payment.Status.PENDING:
            logger.warning(
                "Payment %s is not eligible for verification",
                payment.id,
            )
            raise ValidationError(
                "Payment is not eligible for verification."
            )

        if booking.status != Booking.Status.PAYMENT_PENDING:
            logger.warning(
                "Booking %s is not awaiting payment",
                booking.id,
            )
            raise ValidationError(
                "Booking is not awaiting payment."
            )

        expected_amount = int(payment.amount * 100)

    # Verify checkout signature with Razorpay.
    client = get_razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

        provider_payment = client.payment.fetch(
            razorpay_payment_id
        )

    except razorpay.errors.SignatureVerificationError as exc:
        logger.error(
            "Razorpay signature verification failed for booking %s",
            booking_id,
        )
        raise ValidationError(
            "Invalid Razorpay payment signature."
        ) from exc

    except Exception:
        logger.exception(
            "Razorpay API verification failed for booking %s",
            booking_id,
        )
        raise ValidationError(
            "Unable to verify payment with Razorpay. Try again later."
        )

    # Validate provider payment details.
    if str(provider_payment.get("order_id")) != str(razorpay_order_id):
        logger.warning(
            "Razorpay order mismatch for booking %s",
            booking_id,
        )
        raise ValidationError(
            "Payment does not belong to the expected order."
        )

    if provider_payment.get("amount") != expected_amount:
        logger.warning(
            "Payment amount mismatch for booking %s",
            booking_id,
        )
        raise ValidationError(
            "Payment amount does not match the booking."
        )

    if provider_payment.get("currency") != "INR":
        logger.warning(
            "Unexpected payment currency for booking %s",
            booking_id,
        )
        raise ValidationError("Unexpected payment currency.")

    if provider_payment.get("status") != "captured":
        logger.warning(
            "Payment not captured for booking %s",
            booking_id,
        )
        raise ValidationError(
            "Payment is not captured yet. Booking remains unconfirmed."
        )

    # Second transaction: lock and recheck state.
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(
            id=booking_id,
            user=user,
        )

        payment = Payment.objects.select_for_update().get(
            id=payment.id,
        )

        if payment.status == Payment.Status.SUCCEEDED:
            if payment.provider_payment_id == razorpay_payment_id:
                logger.info(
                    "Payment already completed by another request for booking %s",
                    booking.id,
                )
                return {
                    "detail": "Payment already verified.",
                    "booking_id": booking.id,
                    "payment_id": payment.id,
                    "payment_status": payment.status,
                    "booking_status": booking.status,
                }

            logger.warning(
                "Another payment succeeded for booking %s",
                booking.id,
            )
            raise ValidationError(
                "A different payment has already succeeded."
            )

        if payment.status != Payment.Status.PENDING:
            logger.warning(
                "Payment %s changed during verification",
                payment.id,
            )
            raise ValidationError(
                "Payment status changed during verification."
            )

        if booking.status != Booking.Status.PAYMENT_PENDING:
            logger.warning(
                "Booking %s changed during payment verification",
                booking.id,
            )
            raise ValidationError(
                "Booking status changed during verification."
            )

        payment.status = Payment.Status.SUCCEEDED
        payment.provider_payment_id = razorpay_payment_id

        payment.save(
            update_fields=[
                "status",
                "provider_payment_id",
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
            "Payment successful and booking %s confirmed. "
            "Payment ID: %s",
            booking.id,
            payment.id,
        )

    return {
        "detail": "Payment verified successfully.",
        "booking_id": booking.id,
        "payment_id": payment.id,
        "payment_status": payment.status,
        "booking_status": booking.status,
    }

