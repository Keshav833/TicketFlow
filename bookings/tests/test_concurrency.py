
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from datetime import timedelta
from decimal import Decimal

from events.models import Venue, Event, Seat, TicketTier, EventSeat
from bookings.models import Booking, BookingItem, ConfirmedSeat, Hold
from bookings.services import create_seat_hold, reserve_confirmed_seats


User = get_user_model()


class ConcurrentSeatHoldTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Concurrency test must run against PostgreSQL.")

        self.user_a = User.objects.create_user(
            username="concurrent_user_a",
            password="test-password-123",
        )
        self.user_b = User.objects.create_user(
            username="concurrent_user_b",
            password="test-password-456",
        )

        self.venue = Venue.objects.create(
            name="Concurrency Test Venue",
            address="123 Test Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)
        self.event = Event.objects.create(
            name="Concurrency Test Event",
            venue=self.venue,
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )

        self.seat = Seat.objects.create(
            venue=self.venue,
            row="Z",
            number=99,
        )

        self.tier = TicketTier.objects.create(
            event=self.event,
            name="Standard",
            price=Decimal("499.00"),
        )

        self.event_seat = EventSeat.objects.create(
            event=self.event,
            seat=self.seat,
            ticket_tier=self.tier,
        )

    def test_only_one_user_can_hold_the_same_seat(self):
        barrier = Barrier(2)

        def attempt_hold(user_id):
            close_old_connections()
            try:
                user = User.objects.get(id=user_id)
                barrier.wait(timeout=10)

                try:
                    booking = create_seat_hold(
                        user=user,
                        event_id=self.event.id,
                        event_seat_ids=[self.event_seat.id],
                    )
                    return ("success", booking.id)
                except Exception as exc:
                    return ("rejected", str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt_hold, self.user_a.id),
                executor.submit(attempt_hold, self.user_b.id),
            ]
            results = [future.result(timeout=20) for future in futures]

        self.assertEqual(
            sum(result[0] == "success" for result in results),
            1,
            msg=f"Expected exactly one successful hold, got: {results}",
        )

        self.assertEqual(
            Hold.objects.filter(
                event_seat=self.event_seat,
                status=Hold.Status.ACTIVE,
            ).count(),
            1,
        )

        self.assertEqual(
            BookingItem.objects.filter(
                event_seat=self.event_seat,
                booking__status=Booking.Status.HELD,
            ).count(),
            1,
        )

    def test_only_one_pending_booking_can_allocate_the_same_seat(self):
        first_booking = Booking.objects.create(
            user=self.user_a,
            status=Booking.Status.PAYMENT_PENDING,
            total_amount=Decimal("499.00"),
        )
        second_booking = Booking.objects.create(
            user=self.user_b,
            status=Booking.Status.PAYMENT_PENDING,
            total_amount=Decimal("499.00"),
        )
        BookingItem.objects.create(
            booking=first_booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )
        BookingItem.objects.create(
            booking=second_booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )
        barrier = Barrier(2)

        def attempt_allocation(booking_id):
            close_old_connections()
            try:
                with transaction.atomic():
                    booking = Booking.objects.get(pk=booking_id)
                    barrier.wait(timeout=10)
                    reserve_confirmed_seats(booking=booking)
                return "allocated"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt_allocation, booking_id)
                for booking_id in (first_booking.id, second_booking.id)
            ]
            results = [future.result(timeout=20) for future in futures]

        self.assertCountEqual(results, ["allocated", "rejected"])
        self.assertEqual(
            ConfirmedSeat.objects.filter(event_seat=self.event_seat).count(),
            1,
        )
