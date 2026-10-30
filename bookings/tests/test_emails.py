from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.core import mail

from users.models import User
from events.models import Venue, Event, Seat, TicketTier, EventSeat

from bookings.models import Booking, BookingItem, Payment, Ticket
from bookings.ticket_services import generate_tickets
from bookings.email_services import (
    send_booking_confirmation_email,
    send_confirmation_safely,
)


class TicketConfirmationEmailTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="email_test_user",
            password="test-password",
            email="customer@example.com",
            first_name="Test Customer",
        )

        cls.venue = Venue.objects.create(
            name="TicketFlow Test Venue"
        )

        now = timezone.now()

        cls.event = Event.objects.create(
            name="TicketFlow Test Event",
            venue=cls.venue,
            description="Testing ticket confirmation emails",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=3),
        )

        cls.seat = Seat.objects.create(
            venue=cls.venue,
            row="A",
            number=1,
        )

        cls.tier = TicketTier.objects.create(
            event=cls.event,
            name="Standard",
            price=Decimal("499.00"),
        )

        cls.event_seat = EventSeat.objects.create(
            event=cls.event,
            seat=cls.seat,
            ticket_tier=cls.tier,
        )

    def setUp(self):
        self.booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.CONFIRMED,
            total_amount=Decimal("499.00"),
        )

        self.booking_item = BookingItem.objects.create(
            booking=self.booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        self.payment = Payment.objects.create(
            booking=self.booking,
            provider="razorpay",
            provider_order_id="order_email_test",
            provider_payment_id="pay_email_test",
            idempotency_key=f"email_test_{self.booking.id}",
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("499.00"),
        )

        # Generate ticket and QR image.
        self.tickets = generate_tickets(self.booking.id)

    def test_confirmation_email_is_sent(self):
        result = send_booking_confirmation_email(
            self.booking.id
        )

        self.assertEqual(result, 1)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]

        self.assertEqual(
            email.to,
            ["customer@example.com"],
        )

        self.assertIn(
            "TicketFlow",
            email.subject,
        )

        self.assertIn(
            "TicketFlow Test Event",
            email.body,
        )

        self.assertIn(
            "TKT-",
            email.body,
        )

    def test_confirmation_email_contains_qr_attachment(self):
        send_booking_confirmation_email(
            self.booking.id
        )

        email = mail.outbox[0]

        self.assertEqual(len(email.attachments), 1)

        attachment = email.attachments[0]

        self.assertTrue(
            attachment[0].endswith(".png")
        )

        self.assertEqual(
            attachment[2],
            "image/png",
        )

    def test_unconfirmed_booking_does_not_send_email(self):
        self.booking.status = Booking.Status.PAYMENT_PENDING
        self.booking.save(update_fields=["status"])

        result = send_booking_confirmation_email(
            self.booking.id
        )

        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_email_does_not_send_email(self):
        self.user.email = ""
        self.user.save(update_fields=["email"])

        result = send_booking_confirmation_email(
            self.booking.id
        )

        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_failure_does_not_raise_exception(self):
        from unittest.mock import patch

        with patch(
            "bookings.email_services.send_booking_confirmation_email",
            side_effect=Exception("SMTP connection failed"),
        ):
            result = send_confirmation_safely(
                self.booking.id
            )

        self.assertIsNone(result)

        self.booking.refresh_from_db()

        self.assertEqual(
            self.booking.status,
            Booking.Status.CONFIRMED,
        )