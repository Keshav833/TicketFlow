from datetime import timedelta
from decimal import Decimal
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Booking, Hold, Payment, Ticket

logger = logging.getLogger("ticketflow")


def get_cancellation_cutoff_hours() -> int:
    """Return the configured number of hours before event start when cancellation closes."""
    return getattr(settings, "TICKETFLOW_CANCELLATION_CUTOFF_HOURS", 2)


def calculate_refund_amount(booking: Booking) -> Decimal:
    """
    Calculate the refund amount for an eligible confirmed booking.
    Financial calculations are always handled with Decimal precision.
    """
    if booking.status != Booking.Status.CONFIRMED:
        return Decimal("0.00")
    return Decimal(str(booking.total_amount))


def validate_cancellation_eligibility(*, booking: Booking, user) -> None:
    """
    Validate that the given booking is eligible for cancellation by the user.

    Rules:
    1. Authenticated customer must own the booking (or be staff).
    2. Booking must be in a cancellable state (HELD, PAYMENT_PENDING, CONFIRMED).
       - CANCELLED, REFUND_PENDING, REFUNDED states are handled idempotently in the service.
       - EXPIRED bookings cannot be cancelled.
    3. Used tickets cannot be cancelled or refunded.
    4. Confirmed bookings cannot be cancelled after the policy cutoff time prior to event start.
    5. Confirmed bookings must have an eligible succeeded payment record.
    """
    # 1. Ownership validation
    if booking.user_id != user.id and not getattr(user, "is_staff", False):
        raise ValidationError("Booking not found.")

    # 2. Status validation
    if booking.status == Booking.Status.EXPIRED:
        raise ValidationError("Expired bookings cannot be cancelled.")

    if booking.status in {
        Booking.Status.CANCELLED,
        Booking.Status.REFUND_PENDING,
        Booking.Status.REFUNDED,
    }:
        # Handled idempotently by service
        return

    if booking.status not in {
        Booking.Status.HELD,
        Booking.Status.PAYMENT_PENDING,
        Booking.Status.CONFIRMED,
    }:
        raise ValidationError(f"Booking in status '{booking.status}' cannot be cancelled.")

    # For held or payment_pending bookings, no tickets or payments need refund validation
    if booking.status in {Booking.Status.HELD, Booking.Status.PAYMENT_PENDING}:
        return

    # 3. Prevent cancellation if any tickets were already checked in / used
    if Ticket.objects.filter(
        booking_item__booking=booking,
        status=Ticket.Status.USED,
    ).exists():
        raise ValidationError("Used tickets cannot be cancelled or refunded.")

    # 4. Check cutoff time policy
    cutoff_hours = get_cancellation_cutoff_hours()
    cutoff_threshold = timezone.now() + timedelta(hours=cutoff_hours)

    items = booking.items.select_related("event_seat__event")
    for item in items:
        event = item.event_seat.event
        if event.starts_at <= cutoff_threshold:
            raise ValidationError(
                f"Bookings cannot be cancelled within {cutoff_hours} hours of the event start time."
            )

    # 5. Payment check for confirmed booking
    succeeded_payment = Payment.objects.filter(
        booking=booking,
        status=Payment.Status.SUCCEEDED,
    ).exists()
    if not succeeded_payment:
        raise ValidationError("No successful payment is available for refund.")
