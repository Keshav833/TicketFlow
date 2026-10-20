
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from bookings.services import start_booking_payment

from events.models import (
    Venue,
    Event,
    Seat,
    TicketTier,
    EventSeat,
)
from bookings.models import Booking, BookingItem, Hold
from bookings.services import expire_stale_holds


User = get_user_model()


class ExpireStaleHoldsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="expiry_test_user",
            password="test-password-123",
        )

        cls.venue = Venue.objects.create(
            name="Test Venue",
            address="123 Test Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)

        cls.event = Event.objects.create(
            name="Test Event",
            venue=cls.venue,
            description="Expiry test event",
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )

        cls.seat = Seat.objects.create(
            venue=cls.venue,
            row="F",
            number=5,
        )

        cls.ticket_tier = TicketTier.objects.create(
            event=cls.event,
            name="Standard",
            price=Decimal("499.00"),
        )

        cls.event_seat = EventSeat.objects.create(
            event=cls.event,
            seat=cls.seat,
            ticket_tier=cls.ticket_tier,
        )

    def create_booking_and_hold(self, expires_at):
        booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.HELD,
            total_amount=Decimal("499.00"),
        )

        BookingItem.objects.create(
            booking=booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        hold = Hold.objects.create(
            event_seat=self.event_seat,
            user=self.user,
            booking=booking,
            status=Hold.Status.ACTIVE,
            expires_at=expires_at,
        )

        return booking, hold

    def test_expired_hold_and_booking_become_expired(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() - timedelta(minutes=1)
        )

        count = expire_stale_holds()

        hold.refresh_from_db()
        booking.refresh_from_db()

        self.assertEqual(count, 1)
        self.assertEqual(hold.status, Hold.Status.EXPIRED)
        self.assertEqual(booking.status, Booking.Status.EXPIRED)

    def test_future_hold_remains_active(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() + timedelta(minutes=5)
        )

        count = expire_stale_holds()

        hold.refresh_from_db()
        booking.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(hold.status, Hold.Status.ACTIVE)
        self.assertEqual(booking.status, Booking.Status.HELD)

    def test_running_expiry_twice_is_idempotent(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() - timedelta(minutes=1)
        )

        first_count = expire_stale_holds()
        second_count = expire_stale_holds()

        hold.refresh_from_db()
        booking.refresh_from_db()

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(hold.status, Hold.Status.EXPIRED)
        self.assertEqual(booking.status, Booking.Status.EXPIRED)


    def test_valid_booking_can_enter_payment(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() + timedelta(minutes=5)
        )

        result = start_booking_payment(
            user=self.user,
            booking_id=booking.id,
        )

        booking.refresh_from_db()

        self.assertEqual(
            booking.status,
            Booking.Status.PAYMENT_PENDING,
        )
        self.assertEqual(result.id, booking.id)

    def test_expired_hold_cannot_enter_payment(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() - timedelta(minutes=1)
        )

        with self.assertRaises(ValidationError):
            start_booking_payment(
                user=self.user,
                booking_id=booking.id,
            )

        booking.refresh_from_db()
        hold.refresh_from_db()

        self.assertEqual(
            booking.status,
            Booking.Status.EXPIRED,
        )
        self.assertEqual(
            hold.status,
            Hold.Status.EXPIRED,
        )

    def test_user_cannot_start_payment_for_another_users_booking(self):
        booking, hold = self.create_booking_and_hold(
            timezone.now() + timedelta(minutes=5)
        )

        another_user = User.objects.create_user(
            username="another_test_user",
            password="test-password-456",
        )

        with self.assertRaises(ValidationError):
            start_booking_payment(
                user=another_user,
                booking_id=booking.id,
            )

        booking.refresh_from_db()

        self.assertEqual(
            booking.status,
            Booking.Status.HELD,
        )
