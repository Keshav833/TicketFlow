"""Authoritative Razorpay payment reconciliation.

This module never accepts browser state as proof of payment.  It queries
Razorpay, then rechecks the local booking/hold state under database locks
before applying an allowed transition.
"""

from decimal import Decimal
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import (
    Booking,
    Hold,
    Payment,
    PaymentReconciliationAttempt,
)
from bookings.outbox import create_booking_fulfillment_outbox, create_late_payment_refund_outbox
from bookings.refund_services import create_late_payment_refund
from bookings.services import reserve_confirmed_seats, transition_booking

logger = logging.getLogger(__name__)


def _snapshot(entity):
    return {
        key: entity[key]
        for key in ("id", "order_id", "amount", "currency", "status", "created_at")
        if key in entity
    }


def _record(*, payment, source, outcome, initiated_by=None, snapshot=None, detail=""):
    return PaymentReconciliationAttempt.objects.create(
        payment=payment,
        initiated_by=initiated_by,
        source=source,
        outcome=outcome,
        provider_snapshot=snapshot or {},
        detail=detail[:500],
    )


def _valid_active_holds(booking):
    """Lock and validate every held seat before confirming a recovered capture."""
    holds = list(Hold.objects.select_for_update().filter(booking=booking).order_by("event_seat_id"))
    expected = set(booking.items.values_list("event_seat_id", flat=True))
    actual = {
        hold.event_seat_id
        for hold in holds
        if hold.status == Hold.Status.ACTIVE and hold.expires_at > timezone.now()
    }
    return bool(expected) and actual == expected, holds


def _queue_late_capture_refund(*, booking, payment, provider_payment_id):
    """Persist a captured-but-unallocatable payment and queue one refund."""
    payment.provider_payment_id = provider_payment_id
    payment.status = Payment.Status.REFUND_PENDING
    payment.save(update_fields=["provider_payment_id", "status", "updated_at"])
    if booking.status in {Booking.Status.HELD, Booking.Status.PAYMENT_PENDING}:
        for hold in booking.holds.filter(status=Hold.Status.ACTIVE):
            hold.status = Hold.Status.EXPIRED
            hold.save(update_fields=["status"])
        transition_booking(booking=booking, new_status=Booking.Status.EXPIRED)
    refund = create_late_payment_refund(payment=payment)
    create_late_payment_refund_outbox(payment, refund=refund)
    return refund


def _apply_captured_payment(*, payment_id, provider_payment):
    """Confirm only a still-valid booking; otherwise queue a late-capture refund."""
    provider_payment_id = str(provider_payment.get("id", ""))
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("booking").get(pk=payment_id)
        booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
        expected_amount = int(payment.amount * Decimal("100"))
        if (
            not provider_payment_id
            or str(provider_payment.get("order_id")) != str(payment.provider_order_id)
            or provider_payment.get("amount") != expected_amount
            or provider_payment.get("currency") != "INR"
        ):
            raise ValidationError("Provider payment does not match the local payment attempt.")

        if payment.status == Payment.Status.SUCCEEDED:
            if payment.provider_payment_id == provider_payment_id:
                return PaymentReconciliationAttempt.Outcome.NO_CHANGE, "Payment was already confirmed."
            raise ValidationError("A different payment was already confirmed for this booking.")
        if payment.status in {Payment.Status.REFUND_PENDING, Payment.Status.REFUNDED}:
            return PaymentReconciliationAttempt.Outcome.NO_CHANGE, "Payment is already in refund recovery."

        # A capture after cancellation, expiry, or an invalid/expired hold is
        # real money but cannot be used to claim inventory.
        holds_valid, _holds = _valid_active_holds(booking)
        if booking.status != Booking.Status.PAYMENT_PENDING or not holds_valid:
            _queue_late_capture_refund(
                booking=booking,
                payment=payment,
                provider_payment_id=provider_payment_id,
            )
            return PaymentReconciliationAttempt.Outcome.REFUND_QUEUED, "Captured after booking eligibility ended."

        try:
            reserve_confirmed_seats(booking=booking)
        except ValidationError:
            _queue_late_capture_refund(
                booking=booking,
                payment=payment,
                provider_payment_id=provider_payment_id,
            )
            return PaymentReconciliationAttempt.Outcome.REFUND_QUEUED, "Captured payment could not allocate inventory."

        payment.provider_payment_id = provider_payment_id
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=["provider_payment_id", "status", "updated_at"])
        transition_booking(booking=booking, new_status=Booking.Status.CONFIRMED)
        booking.holds.filter(status=Hold.Status.ACTIVE).update(status=Hold.Status.CONVERTED)
        create_booking_fulfillment_outbox(booking)
        return PaymentReconciliationAttempt.Outcome.CONFIRMED, "Captured payment confirmed booking."


def _provider_payment_for_attempt(payment):
    """Return a provider payment entity, or None when the provider is still inconclusive."""
    from bookings.payment_services import get_razorpay_client

    client = get_razorpay_client()
    if not payment.provider_order_id:
        return None
    order = client.order.fetch(payment.provider_order_id)
    if order.get("status") in {"created", "attempted"}:
        return None
    payments = client.order.payments(payment.provider_order_id)
    entities = payments.get("items", payments) if isinstance(payments, dict) else payments
    captured = [item for item in (entities or []) if item.get("status") == "captured"]
    if captured:
        # The provider may return multiple attempts; a captured payment is
        # authoritative, and local locks prevent duplicate confirmation.
        return client.payment.fetch(captured[0]["id"])
    failed = [item for item in (entities or []) if item.get("status") == "failed"]
    return failed[0] if failed else None


def reconcile_payment(*, payment_id, source=PaymentReconciliationAttempt.Source.PERIODIC, initiated_by=None):
    """Reconcile one uncertain payment against Razorpay without force-confirming it."""
    payment = Payment.objects.select_related("booking").filter(pk=payment_id).first()
    if payment is None:
        return {"outcome": "missing", "payment_id": payment_id}

    if payment.status in {Payment.Status.SUCCEEDED, Payment.Status.REFUND_PENDING, Payment.Status.REFUNDED}:
        _record(payment=payment, source=source, initiated_by=initiated_by,
                outcome=PaymentReconciliationAttempt.Outcome.NO_CHANGE,
                detail="Payment is already terminal or in refund recovery.")
        return {"outcome": "no_change", "payment_id": payment.id}

    try:
        entity = _provider_payment_for_attempt(payment)
    except Exception as exc:
        logger.exception("Payment reconciliation provider error for payment %s", payment.id)
        _record(payment=payment, source=source, initiated_by=initiated_by,
                outcome=PaymentReconciliationAttempt.Outcome.ERROR, detail="Provider lookup failed.")
        raise

    if entity is None:
        _record(payment=payment, source=source, initiated_by=initiated_by,
                outcome=PaymentReconciliationAttempt.Outcome.UNCERTAIN,
                detail="Provider has no final payment outcome yet.")
        return {"outcome": "uncertain", "payment_id": payment.id}

    snapshot = _snapshot(entity)
    if entity.get("status") == "captured":
        outcome, detail = _apply_captured_payment(payment_id=payment.id, provider_payment=entity)
        payment.refresh_from_db()
        _record(payment=payment, source=source, initiated_by=initiated_by,
                outcome=outcome, snapshot=snapshot, detail=detail)
        return {"outcome": outcome, "payment_id": payment.id}

    if entity.get("status") == "failed":
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.id)
            if payment.status in {Payment.Status.PENDING, Payment.Status.CREATING}:
                payment.provider_payment_id = str(entity.get("id", ""))
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["provider_payment_id", "status", "updated_at"])
        _record(payment=payment, source=source, initiated_by=initiated_by,
                outcome=PaymentReconciliationAttempt.Outcome.FAILED,
                snapshot=snapshot, detail="Provider reports payment failure.")
        return {"outcome": "failed", "payment_id": payment.id}

    _record(payment=payment, source=source, initiated_by=initiated_by,
            outcome=PaymentReconciliationAttempt.Outcome.UNCERTAIN,
            snapshot=snapshot, detail="Provider payment state is not final.")
    return {"outcome": "uncertain", "payment_id": payment.id}
