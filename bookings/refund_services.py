"""Razorpay refund lifecycle helpers.

Provider calls intentionally occur outside database transactions.  The local
refund ledger is locked before and after every call, while the outbox provides
durable retry.  A request whose provider response is uncertain is *submitted*,
not treated as refunded; a webhook or reconciliation must confirm it.
"""

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP
import logging

import razorpay
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import Booking, Payment, Refund, Ticket

logger = logging.getLogger(__name__)


class RefundProviderPermanentError(Exception):
    """The provider rejected a refund and retrying cannot fix it."""


def _paise(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _provider_timestamp(value):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_provider_metadata(entity):
    """Keep operational fields only; do not persist arbitrary provider data."""
    return {
        key: entity[key]
        for key in ("id", "payment_id", "amount", "currency", "status", "created_at", "notes")
        if key in entity
    }


@transaction.atomic
def create_refund_request(*, payment, amount: Decimal, idempotency_key: str):
    """Create one bounded refund request, or return the existing request."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= Decimal("0.00"):
        raise ValidationError("Refund amount must be greater than zero.")

    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in {
        Payment.Status.SUCCEEDED,
        Payment.Status.REFUND_PENDING,
        Payment.Status.REFUNDED,
    } or not payment.provider_payment_id:
        raise ValidationError("Only captured payments can be refunded.")

    existing = Refund.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    reserved = (
        Refund.objects.select_for_update()
        .filter(payment=payment)
        .exclude(status=Refund.Status.FAILED)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    remaining = payment.amount - reserved
    if amount > remaining:
        raise ValidationError("Refund amount exceeds the remaining refundable balance.")

    return Refund.objects.create(
        booking_id=payment.booking_id,
        payment=payment,
        amount=amount,
        currency="INR",
        idempotency_key=idempotency_key,
    )


def create_cancellation_refund(*, payment, amount: Decimal):
    return create_refund_request(
        payment=payment,
        amount=amount,
        idempotency_key=f"booking-cancellation:{payment.booking_id}:{payment.id}",
    )


def create_late_payment_refund(*, payment):
    return create_refund_request(
        payment=payment,
        amount=payment.amount,
        idempotency_key=f"late-payment:{payment.id}",
    )


def _refresh_payment_and_booking(payment):
    processed = (
        Refund.objects.filter(payment=payment, status=Refund.Status.PROCESSED)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    if processed < payment.amount:
        return

    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
    if booking.status == Booking.Status.REFUND_PENDING:
        from bookings.services import transition_booking

        transition_booking(booking=booking, new_status=Booking.Status.REFUNDED)
        Ticket.objects.filter(
            booking_item__booking=booking,
            status=Ticket.Status.ISSUED,
        ).update(status=Ticket.Status.CANCELLED)


def apply_provider_refund_update(*, refund_id, entity):
    """Apply an authoritative provider outcome without allowing stale regressions."""
    status = str(entity.get("status", "")).lower()
    provider_refund_id = str(entity.get("id", ""))
    if status not in {"processed", "failed", "pending"} or not provider_refund_id:
        raise ValidationError("Unsupported Razorpay refund state.")

    provider_created_at = _provider_timestamp(entity.get("created_at"))
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund_id)
        if refund.provider_refund_id and refund.provider_refund_id != provider_refund_id:
            raise ValidationError("Refund provider reference does not match.")
        if refund.status == Refund.Status.PROCESSED:
            return refund
        if (
            refund.provider_created_at
            and provider_created_at
            and provider_created_at < refund.provider_created_at
        ):
            return refund

        now = timezone.now()
        refund.provider_refund_id = provider_refund_id
        refund.provider_status = status
        refund.provider_created_at = provider_created_at or refund.provider_created_at
        refund.provider_metadata = _safe_provider_metadata(entity)
        refund.failure_reason = ""
        refund.failed_at = None

        if status == "processed":
            refund.status = Refund.Status.PROCESSED
            refund.processed_at = now
        elif status == "failed":
            refund.status = Refund.Status.FAILED
            refund.failed_at = now
            refund.failure_reason = str(entity.get("failure_reason") or "Provider rejected refund.")[:5000]
        else:
            refund.status = Refund.Status.SUBMITTED
            refund.submitted_at = refund.submitted_at or now

        refund.save()
        payment = refund.payment
        if provider_refund_id and not payment.provider_refund_id:
            payment.provider_refund_id = provider_refund_id
            payment.save(update_fields=["provider_refund_id", "updated_at"])
        if refund.status == Refund.Status.PROCESSED:
            _refresh_payment_and_booking(payment)
        return refund


def mark_refund_failed(*, refund_id, reason):
    """Record a non-retryable provider rejection without falsifying payment state."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund_id)
        if refund.status == Refund.Status.PROCESSED:
            return refund
        refund.status = Refund.Status.FAILED
        refund.failed_at = timezone.now()
        refund.failure_reason = str(reason)[:5000]
        refund.save(update_fields=["status", "failed_at", "failure_reason", "updated_at"])
        return refund


def _find_provider_refund(client, refund):
    if refund.provider_refund_id:
        try:
            return client.refund.fetch(refund.provider_refund_id)
        except AttributeError:
            return None

    try:
        results = client.payment.all_refunds(refund.payment.provider_payment_id)
    except AttributeError:
        return None
    entities = results.get("items", results) if isinstance(results, dict) else results
    for entity in entities or []:
        if (entity.get("notes") or {}).get("ticketflow_refund_key") == refund.idempotency_key:
            return entity
    return None


def reconcile_refund(refund_id):
    """Fetch a known/possibly submitted refund from Razorpay and apply its state."""
    refund = Refund.objects.select_related("payment").filter(pk=refund_id).first()
    if refund is None or refund.status == Refund.Status.PROCESSED:
        return refund
    if not refund.payment.provider_payment_id:
        raise RefundProviderPermanentError("Refund payment is missing its provider payment ID.")

    from bookings.payment_services import get_razorpay_client

    entity = _find_provider_refund(get_razorpay_client(), refund)
    if entity:
        return apply_provider_refund_update(refund_id=refund.id, entity=entity)
    return refund


def submit_refund(refund_id):
    """Submit a pending refund once; provider confirmation remains asynchronous."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund_id)
        if refund.status in {Refund.Status.PROCESSED, Refund.Status.FAILED}:
            return refund
        if refund.status == Refund.Status.SUBMITTED:
            return refund
        if not refund.payment.provider_payment_id:
            raise RefundProviderPermanentError("Refund payment is missing its provider payment ID.")
        refund.status = Refund.Status.SUBMITTED
        refund.submitted_at = timezone.now()
        refund.save(update_fields=["status", "submitted_at", "updated_at"])
        provider_payment_id = refund.payment.provider_payment_id
        amount = refund.amount
        key = refund.idempotency_key

    from bookings.payment_services import get_razorpay_client

    try:
        entity = get_razorpay_client().payment.refund(
            provider_payment_id,
            {"amount": _paise(amount), "notes": {"ticketflow_refund_key": key}},
        )
    except razorpay.errors.BadRequestError as exc:
        mark_refund_failed(refund_id=refund_id, reason=exc)
        raise RefundProviderPermanentError("Razorpay rejected the refund request.") from exc
    except Exception:
        # A request may have reached Razorpay.  It remains submitted and is
        # reconciled instead of being blindly sent a second time.
        logger.exception("Razorpay refund submission outcome is uncertain for refund %s", refund_id)
        raise
    # Submission means Razorpay accepted the request; it is not financial
    # completion.  Keep it in the submitted state until a later provider fetch
    # or a signed webhook confirms ``processed``.
    entity = {**entity, "status": "pending"}
    return apply_provider_refund_update(refund_id=refund_id, entity=entity)
