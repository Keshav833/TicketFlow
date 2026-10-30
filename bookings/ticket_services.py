from django.db import transaction
import qrcode
from io import BytesIO
from django.core.files import File
from bookings.models import (
    Booking,
    BookingItem,
    Payment,
    Ticket,
)


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