from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from events.models import EventSeat
from .models import Booking, BookingItem, Hold


@transaction.atomic
def create_seat_hold(*, user, event_id, event_seat_ids):
    now = timezone.now()

    # Lock seats in a consistent order to reduce deadlocks.
    seats = list(
        EventSeat.objects
        .select_for_update()
        .filter(
            event_id=event_id,
            id__in=event_seat_ids,
        )
        .select_related("ticket_tier")
        .order_by("id")
    )

    if len(seats) != len(event_seat_ids):
        raise ValidationError(
            "One or more seats are invalid for this event."
        )

    seat_ids = [seat.id for seat in seats]

    # Mark old holds as expired before checking availability.
    Hold.objects.filter(
        event_seat_id__in=seat_ids,
        status=Hold.Status.ACTIVE,
        expires_at__lte=now,
    ).update(status=Hold.Status.EXPIRED)

    # Reject seats that are still held.
    active_holds = Hold.objects.filter(
        event_seat_id__in=seat_ids,
        status=Hold.Status.ACTIVE,
        expires_at__gt=now,
    ).exists()

    if active_holds:
        raise ValidationError(
            "One or more seats are currently held."
        )

    # Reject seats already sold through a confirmed booking.
    sold_seats = BookingItem.objects.filter(
        event_seat_id__in=seat_ids,
        booking__status=Booking.Status.CONFIRMED,
    ).exists()

    if sold_seats:
        raise ValidationError(
            "One or more seats have already been booked."
        )

    total = sum(
        (seat.ticket_tier.price for seat in seats),
        Decimal("0.00"),
    )

    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.HELD,
        total_amount=total,
    )

    BookingItem.objects.bulk_create([
        BookingItem(
            booking=booking,
            event_seat=seat,
            price=seat.ticket_tier.price,
        )
        for seat in seats
    ])

    expires_at = now + timedelta(minutes=10)

    Hold.objects.bulk_create([
        Hold(
            event_seat=seat,
            user=user,
            booking=booking,
            status=Hold.Status.ACTIVE,
            expires_at=expires_at,
        )
        for seat in seats
    ])

    return booking