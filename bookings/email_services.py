
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.core.files.base import ContentFile


# Understand what this service does
# 1. Fetches the booking and related information.
# 2. Checks that the booking is confirmed.
# 3. Checks that the user has an email address.
# 4. Collects all tickets belonging to the booking.
# 5. Builds the confirmation message.
# 6. Attaches each ticket's QR image.
# 7. Sends one email to the booking owner.

def send_booking_confirmation_email(booking_id):
    from bookings.models import Booking

    booking = (
        Booking.objects
        .select_related("user")
        .prefetch_related(
            "items__event_seat__event__venue",
            "items__event_seat__seat",
            "items__ticket",
        )
        .get(id=booking_id)
    )

    if booking.status != Booking.Status.CONFIRMED:
        return False

    if not booking.user.email:
        return False

    tickets = []

    for item in booking.items.all():
        ticket = getattr(item, "ticket", None)

        if ticket is None:
            continue

        event_seat = item.event_seat
        event = event_seat.event
        seat = event_seat.seat

        tickets.append({
            "ticket_number": ticket.ticket_number,
            "event_name": event.name,
            "event_date": event.starts_at,
            "venue": event.venue.name,
            "seat": f"{seat.row}{seat.number}",
            "qr_code": ticket.qr_code,
        })

    if not tickets:
        return False

    subject = "Your TicketFlow booking is confirmed!"

    message = [
        f"Hello {booking.user.first_name or booking.user.username},",
        "",
        "Your booking has been confirmed.",
        f"Booking ID: {booking.id}",
        "",
        "Your tickets:",
        "",
    ]

    for ticket in tickets:
        message.extend([
            f"Ticket: {ticket['ticket_number']}",
            f"Event: {ticket['event_name']}",
            f"Date: {ticket['event_date']}",
            f"Venue: {ticket['venue']}",
            f"Seat: {ticket['seat']}",
            "",
        ])

    message.extend([
        "Please find your ticket QR codes attached.",
        "",
        "Thank you for booking with TicketFlow!",
    ])

    email = EmailMultiAlternatives(
        subject=subject,
        body="\n".join(message),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[booking.user.email],
    )

    for ticket in tickets:
        qr_file = ticket["qr_code"]

        if not qr_file:
            continue

        qr_file.open("rb")
        try:
            email.attach(
                f"{ticket['ticket_number']}.png",
                qr_file.read(),
                "image/png",
            )
        finally:
            qr_file.close()

    return email.send()


def send_confirmation_safely(booking_id):
    try:
        send_booking_confirmation_email(booking_id)
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception(
            "Failed to send confirmation email for booking %s",
            booking_id,
        )