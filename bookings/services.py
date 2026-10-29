from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from events.models import EventSeat
from .models import Booking, BookingItem, Hold


def transition_booking(*, booking, new_status):
    """
    Validate and apply an allowed booking status transition.
    """
    allowed_transitions = {
        Booking.Status.HELD: {
            Booking.Status.PAYMENT_PENDING,
            Booking.Status.EXPIRED,
            Booking.Status.CANCELLED,
        },
        Booking.Status.PAYMENT_PENDING: {
            Booking.Status.CONFIRMED,
            Booking.Status.EXPIRED,
            Booking.Status.CANCELLED,
        },
        Booking.Status.CONFIRMED: {
            Booking.Status.REFUNDED,
        },
        Booking.Status.EXPIRED: set(),
        Booking.Status.CANCELLED: set(),
        Booking.Status.REFUNDED: set(),
        
    }

    if new_status not in allowed_transitions[booking.status]:
        raise ValidationError(
            f"Invalid booking transition: "
            f"{booking.status} -> {new_status}"
        )

    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])

    return booking

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

@transaction.atomic
def expire_stale_holds():
    """Expire overdue holds and their still-held bookings."""
    now = timezone.now()

    expired_holds = list(
        Hold.objects
        .select_for_update()
        .filter(
            status="active",
            expires_at__lte=now,
        )
        .order_by("id")
    )

    if not expired_holds:
        return 0

    hold_ids = [hold.id for hold in expired_holds]
    booking_ids = {
        hold.booking_id for hold in expired_holds
    }

    Hold.objects.filter(
        id__in=hold_ids,
        status="active",
    ).update(status="expired")

    Booking.objects.filter(
        id__in=booking_ids,
        status="held",
    ).update(status="expired")

    return len(hold_ids)




def start_booking_payment(*, user, booking_id):
    error_message = None
    booking = None

    with transaction.atomic():
        booking = (
            Booking.objects
            .select_for_update()
            .filter(id=booking_id, user=user)
            .first()
        )

        if booking is None:
            error_message = "Booking not found."

        elif booking.status != Booking.Status.HELD:
            error_message = "This booking cannot enter payment."

        else:
            now = timezone.now()

            holds = list(
                Hold.objects
                .select_for_update()
                .filter(booking=booking)
                .order_by("id")
            )

            booking_seat_ids = set(
                booking.items.values_list(
                    "event_seat_id",
                    flat=True,
                )
            )

            valid_seat_ids = {
                hold.event_seat_id
                for hold in holds
                if (
                    hold.status == Hold.Status.ACTIVE
                    and hold.expires_at > now
                )
            }

            if (
                not booking_seat_ids
                or valid_seat_ids != booking_seat_ids
            ):
                Hold.objects.filter(
                    booking=booking,
                    status=Hold.Status.ACTIVE,
                    expires_at__lte=now,
                ).update(status=Hold.Status.EXPIRED)

                transition_booking(
                    booking=booking,
                    new_status=Booking.Status.EXPIRED,
                )

                error_message = (
                    "Booking hold expired. Please create a new booking."
                )

            else:
                transition_booking(
                    booking=booking,
                    new_status=Booking.Status.PAYMENT_PENDING,
                )

    # The transaction has committed before raising the error.
    if error_message:
        raise ValidationError(error_message)

    return booking
