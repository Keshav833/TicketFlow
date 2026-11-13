import logging

logger = logging.getLogger(__name__)
from django.db import transaction
import qrcode
from io import BytesIO
from django.core.files import File
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound
from bookings.models import (
    Booking,
    BookingItem,
    Payment,
    Ticket,
)


class TicketCheckInConflict(APIException):
    status_code = 409
    default_detail = "Ticket cannot be checked in."
    default_code = "ticket_check_in_conflict"


@transaction.atomic
def generate_tickets(booking_id):
    booking = Booking.objects.select_for_update().get(
        id=booking_id
    )

    if booking.status != Booking.Status.CONFIRMED:
        raise ValueError("Booking is not confirmed.")

    payment_succeeded = Payment.objects.filter(
        booking=booking,
        status=Payment.Status.SUCCEEDED,
    ).exists()

    if not payment_succeeded:
        raise ValueError("Booking payment has not succeeded.")

    tickets = []

    booking_items = BookingItem.objects.filter(
        booking=booking
    )

    for item in booking_items:
        ticket, created = Ticket.objects.get_or_create(
            booking_item=item,
            defaults={
                "ticket_number": f"TKT-{item.id}-{booking.id}",
            },
        )

        # Generate QR only when it doesn't already exist.
        if not ticket.qr_code:
            generate_ticket_qr(ticket)

        tickets.append(ticket)

    return tickets


def generate_ticket_qr(ticket):
    # Avoid regenerating an existing QR code.
    if ticket.qr_code:
        return ticket

    qr_data = str(ticket.verification_token)

    qr = qrcode.make(qr_data)

    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)

    filename = f"{ticket.ticket_number}.png"

    ticket.qr_code.save(
        filename,
        File(buffer),
        save=True,
    )

    buffer.close()

    return ticket



@transaction.atomic
def check_in_ticket(verification_token):
    try:
        ticket = (
            Ticket.objects
            .select_for_update(of=("self",))
            .select_related(
                "booking_item__booking",
                "booking_item__event_seat__event",
                "booking_item__event_seat__seat",
            )
            .get(verification_token=verification_token)
        )
    except Ticket.DoesNotExist:
        logger.warning("Check-in attempted with an unknown ticket token")
        raise NotFound("Ticket not found.")

    booking = ticket.booking_item.booking

    # Verify booking status.
    if booking.status != Booking.Status.CONFIRMED:
        logger.warning(
            "Check-in rejected: booking %s is not confirmed",
            booking.id,
        )
        raise TicketCheckInConflict(
            "Booking is not confirmed."
        )

    # Verify successful payment.
    payment_succeeded = Payment.objects.filter(
        booking=booking,
        status=Payment.Status.SUCCEEDED,
    ).exists()

    if not payment_succeeded:
        logger.warning(
            "Check-in rejected: payment not completed for booking %s",
            booking.id,
        )
        raise TicketCheckInConflict(
            "Payment has not been completed."
        )

    # Prevent duplicate check-ins.
    if ticket.status == Ticket.Status.USED:
        logger.warning(
            "Duplicate check-in attempt for ticket %s",
            ticket.ticket_number,
        )
        raise TicketCheckInConflict(
            "Ticket has already been used."
        )

    if ticket.status == Ticket.Status.CANCELLED:
        logger.warning(
            "Check-in rejected: ticket %s is cancelled",
            ticket.ticket_number,
        )
        raise TicketCheckInConflict(
            "Ticket has been cancelled."
        )

    # Mark ticket as used.
    ticket.status = Ticket.Status.USED
    ticket.used_at = timezone.now()

    ticket.save(
        update_fields=[
            "status",
            "used_at",
        ]
    )

    event_seat = ticket.booking_item.event_seat

    logger.info(
        "Ticket %s checked in successfully for booking %s",
        ticket.ticket_number,
        booking.id,
    )

    return {
        "detail": "Ticket verified successfully.",
        "ticket_number": ticket.ticket_number,
        "status": ticket.status,
        "event": event_seat.event.name,
        "seat": str(event_seat.seat),
        "used_at": ticket.used_at,
    }
