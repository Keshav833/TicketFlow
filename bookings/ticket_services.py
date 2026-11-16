import logging

logger = logging.getLogger(__name__)
from django.db import transaction
from django.db.models import Exists, OuterRef
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


class TicketFileUnavailable(APIException):
    status_code = 404
    default_detail = "Ticket file is not available."
    default_code = "ticket_file_unavailable"


class TicketFileNotEligible(APIException):
    status_code = 409
    default_detail = "This ticket cannot be downloaded."
    default_code = "ticket_file_not_eligible"


# Customers may keep a copy of issued and already-used tickets.
# Cancelled tickets stay visible for history, but their files are not usable.
CUSTOMER_FILE_STATUSES = {
    Ticket.Status.ISSUED,
    Ticket.Status.USED,
}
QR_STORAGE_PREFIX = "tickets/qr_codes/"


def customer_visible_tickets(user):
    """Tickets the authenticated customer is allowed to see.

    A ticket is visible only when the booking is confirmed and has a
    succeeded payment. Held, pending, expired, cancelled, refunded, and
    failed-payment bookings stay hidden. Individual cancelled tickets on a
    still-confirmed booking remain visible so a partial cancellation can be
    shown without offering a usable file.
    """
    if not getattr(user, "is_authenticated", False):
        return Ticket.objects.none()

    succeeded_payment = Payment.objects.filter(
        booking_id=OuterRef("booking_item__booking_id"),
        status=Payment.Status.SUCCEEDED,
    )
    return (
        Ticket.objects.filter(
            booking_item__booking__user=user,
            booking_item__booking__status=Booking.Status.CONFIRMED,
        )
        .filter(Exists(succeeded_payment))
        .select_related(
            "booking_item__booking",
            "booking_item__event_seat__event__venue",
            "booking_item__event_seat__seat",
            "booking_item__event_seat__ticket_tier",
        )
        .order_by("-issued_at", "-id")
    )


def ensure_customer_file_access(ticket):
    if ticket.status not in CUSTOMER_FILE_STATUSES:
        raise TicketFileNotEligible(
            "This ticket is not eligible for QR retrieval or download."
        )


def stored_qr_name_is_safe(name):
    if not name or not isinstance(name, str):
        return False
    normalized = name.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return False
    safe_name = "/".join(parts)
    return safe_name.startswith(QR_STORAGE_PREFIX) and safe_name != QR_STORAGE_PREFIX


def open_stored_qr(ticket):
    """Open the QR file already stored for this ticket.

    Does not generate a replacement image when the file is missing.
    """
    ensure_customer_file_access(ticket)
    stored = ticket.qr_code
    if not stored or not stored_qr_name_is_safe(stored.name):
        raise TicketFileUnavailable("QR image is not available.")

    storage = stored.storage
    if not storage.exists(stored.name):
        raise TicketFileUnavailable("QR image is not available.")

    return storage.open(stored.name, "rb")


def read_stored_qr(ticket):
    image = open_stored_qr(ticket)
    try:
        return image.read()
    finally:
        image.close()


def ticket_download_filename(ticket_number):
    safe = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in str(ticket_number)
    ).strip("-")
    return f"{safe or 'ticket'}.pdf"


def build_ticket_download(ticket):
    """Build a downloadable ticket document from stored ticket data."""
    ensure_customer_file_access(ticket)
    event_seat = ticket.booking_item.event_seat
    event = event_seat.event
    seat = event_seat.seat
    booking = ticket.booking_item.booking
    lines = [
        "TicketFlow Ticket",
        f"Ticket: {ticket.ticket_number}",
        f"Status: {ticket.get_status_display()}",
        f"Booking: {booking.id}",
        f"Event: {event.name}",
        f"Starts: {event.starts_at.isoformat()}",
        f"Ends: {event.ends_at.isoformat()}",
        f"Venue: {event.venue.name}, {event.venue.city}",
        f"Seat: {seat.row}{seat.number}",
        f"Tier: {event_seat.ticket_tier.name}",
        f"Price: {ticket.booking_item.price}",
    ]
    return _simple_pdf(lines), ticket_download_filename(ticket.ticket_number)


def _pdf_escape(value):
    text = str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.encode("latin-1", "replace").decode("latin-1")


def _simple_pdf(lines):
    commands = ["BT", "/F1 12 Tf", "50 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -18 Td")
        commands.append(f"({_pdf_escape(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        ),
        (
            b"4 0 obj << /Length "
            + str(len(stream)).encode("ascii")
            + b" >> stream\n"
            + stream
            + b"\nendstream endobj\n"
        ),
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)
