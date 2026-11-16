from datetime import timedelta
from decimal import Decimal
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from events.cache import invalidate_seat_availability
from events.models import EventSeat
from .models import Booking, BookingItem, ConfirmedSeat, Hold, Payment, Ticket


logger = logging.getLogger("ticketflow")


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
            Booking.Status.REFUND_PENDING,
        },
        Booking.Status.REFUND_PENDING: {Booking.Status.REFUNDED},
        Booking.Status.EXPIRED: set(),
        Booking.Status.CANCELLED: set(),
        Booking.Status.REFUNDED: set(),
        
    }

    allowed = allowed_transitions.get(booking.status, set())

    if new_status not in allowed:
        raise ValidationError(
             f"Invalid booking transition: {booking.status} -> {new_status}"
        )

    old_status = booking.status
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    transaction.on_commit(
        lambda: logger.info(
            "Booking status changed: booking_id=%s from=%s to=%s",
            booking.id,
            old_status,
            new_status,
        )
    )

    return booking


@transaction.atomic
def cancel_booking(*, user, booking_id):
    """Cancel an unpaid booking or queue a refund for an eligible paid one."""
    booking = (
        Booking.objects.select_for_update()
        .filter(id=booking_id, user=user)
        .first()
    )
    if booking is None:
        raise ValidationError("Booking not found.")

    if booking.status in {Booking.Status.HELD, Booking.Status.PAYMENT_PENDING}:
        booking.holds.filter(status=Hold.Status.ACTIVE).update(
            status=Hold.Status.CANCELLED
        )
        transition_booking(booking=booking, new_status=Booking.Status.CANCELLED)
        return booking

    if booking.status != Booking.Status.CONFIRMED:
        raise ValidationError("This booking cannot be cancelled.")

    if Ticket.objects.filter(
        booking_item__booking=booking,
        status=Ticket.Status.USED,
    ).exists():
        raise ValidationError("Used tickets cannot be refunded.")
    if BookingItem.objects.filter(
        booking=booking,
        event_seat__event__starts_at__lte=timezone.now(),
    ).exists():
        raise ValidationError("Bookings cannot be refunded after the event starts.")

    payment = (
        Payment.objects.select_for_update()
        .filter(booking=booking, status=Payment.Status.SUCCEEDED)
        .first()
    )
    if payment is None:
        raise ValidationError("No successful payment is available for refund.")

    transition_booking(booking=booking, new_status=Booking.Status.REFUND_PENDING)
    payment.status = Payment.Status.REFUND_PENDING
    payment.save(update_fields=["status", "updated_at"])
    from bookings.outbox import create_booking_refund_outbox

    create_booking_refund_outbox(payment)
    return booking


def reserve_confirmed_seats(*, booking):
    """Atomically allocate every seat in a pending booking.

    ``ConfirmedSeat.event_seat`` is one-to-one, so PostgreSQL is the final
    authority that an event seat has only one confirmed booking item.
    """
    if booking.status != Booking.Status.PAYMENT_PENDING:
        raise ValidationError("Booking is not awaiting payment.")

    items = list(
        BookingItem.objects.filter(booking=booking)
        .select_related("event_seat")
        .order_by("event_seat_id")
    )
    if not items:
        raise ValidationError("Booking has no seats to confirm.")

    seat_ids = [item.event_seat_id for item in items]
    locked_seats = list(
        EventSeat.objects.select_for_update()
        .filter(id__in=seat_ids)
        .order_by("id")
    )
    if len(locked_seats) != len(seat_ids):
        raise ValidationError("One or more booking seats no longer exist.")

    items_by_seat = {item.event_seat_id: item for item in items}
    for seat in locked_seats:
        item = items_by_seat[seat.id]
        allocation, created = ConfirmedSeat.objects.get_or_create(
            event_seat=seat,
            defaults={"booking_item": item},
        )
        if not created and allocation.booking_item_id != item.id:
            raise ValidationError(
                "One or more seats have already been confirmed."
            )

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

    # Mark old holds as expired before checking availability. Their bookings
    # must become terminal too: otherwise a late payment could confirm an
    # expired booking after this transaction lets another customer hold the
    # same seat.
    expired_holds = list(
        Hold.objects.select_for_update()
        .filter(
            event_seat_id__in=seat_ids,
            status=Hold.Status.ACTIVE,
            expires_at__lte=now,
        )
        .order_by("id")
    )
    expired_hold_ids = [hold.id for hold in expired_holds]
    expired_booking_ids = {hold.booking_id for hold in expired_holds}

    if expired_hold_ids:
        Hold.objects.filter(id__in=expired_hold_ids).update(
            status=Hold.Status.EXPIRED
        )

    expired_bookings = (
        Booking.objects.select_for_update()
        .filter(
            id__in=expired_booking_ids,
            status__in=[
                Booking.Status.HELD,
                Booking.Status.PAYMENT_PENDING,
            ],
        )
        .order_by("id")
    )
    for expired_booking in expired_bookings:
        transition_booking(
            booking=expired_booking,
            new_status=Booking.Status.EXPIRED,
        )

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

    invalidate_seat_availability(event_id)
    transaction.on_commit(
        lambda: logger.info(
            "Seat hold created: booking_id=%s event_id=%s seat_count=%s",
            booking.id,
            event_id,
            len(seats),
        )
    )
    return booking



@transaction.atomic
def expire_stale_holds():
    """Expire overdue holds and their still-held bookings."""
    now = timezone.now()

    expired_holds = list(
        Hold.objects
        .select_for_update()
        .filter(
            status=Hold.Status.ACTIVE,
            expires_at__lte=now,
        )
        .order_by("id")
    )

    if not expired_holds:
        return 0

    hold_ids = [hold.id for hold in expired_holds]
    event_ids = {hold.event_seat.event_id for hold in expired_holds}
    booking_ids = {
        hold.booking_id for hold in expired_holds
    }

    Hold.objects.filter(
        id__in=hold_ids,
        status=Hold.Status.ACTIVE,
    ).update(status=Hold.Status.EXPIRED)

    bookings = (
        Booking.objects
        .select_for_update()
        .filter(
            id__in=booking_ids,
            status__in=[
                Booking.Status.HELD,
                Booking.Status.PAYMENT_PENDING,
            ],
        )
        .order_by("id")
    )

    for booking in bookings:
        transition_booking(
            booking=booking,
            new_status=Booking.Status.EXPIRED,
        )

    for event_id in event_ids:
        invalidate_seat_availability(event_id)

    transaction.on_commit(
        lambda: logger.info(
            "Expired stale holds: count=%s event_count=%s",
            len(hold_ids),
            len(event_ids),
        )
    )
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
                for event_id in booking.items.values_list(
                    "event_seat__event_id",
                    flat=True,
                ).distinct():
                    invalidate_seat_availability(event_id)

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
