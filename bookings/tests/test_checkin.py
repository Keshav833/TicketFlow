
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound
from rest_framework.test import APIClient
from django.urls import reverse

from django.core.cache import cache

from bookings.models import (
    Booking,
    BookingItem,
    Payment,
    Ticket,
)
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase

from bookings.ticket_services import (
    check_in_ticket,
    TicketCheckInConflict,
)
from events.models import Venue, Event, Seat, TicketTier, EventSeat


User = get_user_model()


class TicketCheckInServiceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="checkin_test_user",
            password="test-password-123",
        )

        cls.venue = Venue.objects.create(
            name="Check-in Test Venue",
            address="123 Test Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)

        cls.event = Event.objects.create(
            name="Check-in Test Event",
            venue=cls.venue,
            description="Testing ticket check-in",
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

    def create_confirmed_ticket(self):
        booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.CONFIRMED,
            total_amount=Decimal("499.00"),
        )

        booking_item = BookingItem.objects.create(
            booking=booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        Payment.objects.create(
            booking=booking,
            provider="razorpay",
            provider_order_id="order_checkin_test",
            provider_payment_id="pay_checkin_test",
            idempotency_key=f"booking_{booking.id}_razorpay",
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("499.00"),
        )

        ticket = Ticket.objects.create(
            booking_item=booking_item,
            ticket_number=f"TKT-CHECKIN-{booking.id}",
        )

        return booking, ticket

    def test_valid_ticket_can_be_checked_in(self):
        booking, ticket = self.create_confirmed_ticket()

        result = check_in_ticket(
            verification_token=ticket.verification_token
        )

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, Ticket.Status.USED)
        self.assertIsNotNone(ticket.used_at)

        self.assertEqual(
            result["detail"],
            "Ticket verified successfully.",
        )
        self.assertEqual(result["ticket_number"], ticket.ticket_number)
        self.assertEqual(result["status"], Ticket.Status.USED)
        self.assertEqual(result["event"], self.event.name)

    def test_already_used_ticket_cannot_be_checked_in_again(self):
        booking, ticket = self.create_confirmed_ticket()

        check_in_ticket(ticket.verification_token)

        with self.assertRaises(APIException):
            check_in_ticket(ticket.verification_token)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, Ticket.Status.USED)

    def test_unknown_ticket_token_returns_not_found(self):
        import uuid

        with self.assertRaises(NotFound):
            check_in_ticket(uuid.uuid4())


class TicketCheckInAPITests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = User.objects.create_user(
            username="checkin_staff",
            password="staff-password-123",
            is_staff=True,
        )

        cls.normal_user = User.objects.create_user(
            username="checkin_normal",
            password="normal-password-123",
        )

        cls.venue = Venue.objects.create(
            name="API Test Venue",
            address="123 API Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)

        cls.event = Event.objects.create(
            name="API Check-in Event",
            venue=cls.venue,
            description="API testing",
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )

        cls.seat = Seat.objects.create(
            venue=cls.venue,
            row="A",
            number=1,
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

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("ticket-check-in")

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_unauthenticated_user_cannot_check_in(self):
        response = self.client.post(
            self.url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_non_staff_user_cannot_check_in(self):
        self.authenticate_as(self.normal_user)

        response = self.client.post(
            self.url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)


    def create_confirmed_ticket(self):
        booking = Booking.objects.create(
            user=self.normal_user,
            status=Booking.Status.CONFIRMED,
            total_amount=Decimal("499.00"),
        )

        booking_item = BookingItem.objects.create(
            booking=booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        Payment.objects.create(
            booking=booking,
            provider="razorpay",
            provider_order_id=f"order_api_{booking.id}",
            provider_payment_id=f"pay_api_{booking.id}",
            idempotency_key=f"booking_{booking.id}_razorpay",
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("499.00"),
        )

        ticket = Ticket.objects.create(
            booking_item=booking_item,
            ticket_number=f"TKT-API-{booking.id}",
        )

        return ticket


    def test_staff_can_check_in_valid_ticket(self):
        self.authenticate_as(self.staff_user)
        ticket = self.create_confirmed_ticket()

        response = self.client.post(
            self.url,
            {"verification_token": str(ticket.verification_token)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.USED)
        self.assertIsNotNone(ticket.used_at)


    def test_invalid_uuid_returns_400(self):
        self.authenticate_as(self.staff_user)

        response = self.client.post(
            self.url,
            {"verification_token": "not-a-valid-uuid"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


    def test_unknown_token_returns_404(self):
        import uuid

        self.authenticate_as(self.staff_user)

        response = self.client.post(
            self.url,
            {"verification_token": str(uuid.uuid4())},
            format="json",
        )

        self.assertEqual(response.status_code, 404)


    def test_already_used_ticket_returns_409(self):
        self.authenticate_as(self.staff_user)
        ticket = self.create_confirmed_ticket()

        first_response = self.client.post(
            self.url,
            {"verification_token": str(ticket.verification_token)},
            format="json",
        )

        second_response = self.client.post(
            self.url,
            {"verification_token": str(ticket.verification_token)},
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 409)


class TicketCheckInConcurrencyTests(TransactionTestCase):

    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            username="concurrent_test_user",
            password="test-password-123",
        )

        venue = Venue.objects.create(
            name="Concurrency Test Venue",
            address="123 Test Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)

        event = Event.objects.create(
            name="Concurrency Test Event",
            venue=venue,
            description="Testing concurrent check-ins",
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )

        seat = Seat.objects.create(
            venue=venue,
            row="A",
            number=1,
        )

        tier = TicketTier.objects.create(
            event=event,
            name="Standard",
            price=Decimal("499.00"),
        )

        event_seat = EventSeat.objects.create(
            event=event,
            seat=seat,
            ticket_tier=tier,
        )

        booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.CONFIRMED,
            total_amount=Decimal("499.00"),
        )

        booking_item = BookingItem.objects.create(
            booking=booking,
            event_seat=event_seat,
            price=Decimal("499.00"),
        )

        Payment.objects.create(
            booking=booking,
            provider="razorpay",
            provider_order_id="order_concurrent_test",
            provider_payment_id="pay_concurrent_test",
            idempotency_key=f"booking_{booking.id}_razorpay",
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("499.00"),
        )

        self.ticket = Ticket.objects.create(
            booking_item=booking_item,
            ticket_number=f"TKT-CONCURRENT-{booking.id}",
        )

    def test_only_one_concurrent_check_in_succeeds(self):
        token = self.ticket.verification_token

        barrier = Barrier(2)

        def perform_check_in():
            close_old_connections()

            try:
                barrier.wait(timeout=10)

                try:
                    check_in_ticket(token)
                    return "success"

                except TicketCheckInConflict:
                    return "conflict"

            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(perform_check_in)
                for _ in range(2)
            ]

            results = [
                future.result(timeout=20)
                for future in futures
            ]

        self.assertEqual(results.count("success"), 1)
        self.assertEqual(results.count("conflict"), 1)

        self.ticket.refresh_from_db()

        self.assertEqual(
            self.ticket.status,
            Ticket.Status.USED,
        )

        self.assertIsNotNone(self.ticket.used_at)


class TicketCheckInThrottleTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("ticket-check-in")

        self.staff_user = User.objects.create_user(
            username="throttle_staff",
            password="test-password-123",
            is_staff=True,
        )

        self.client.force_authenticate(user=self.staff_user)

        # Clear previous throttle records
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_checkin_api_allows_only_10_requests_per_minute(self):

        # First 10 requests should pass throttling.
        for _ in range(10):
            response = self.client.post(
                self.url,
                {
                    "verification_token": str(uuid.uuid4()),
                },
                format="json",
            )

            # Unknown token returns 404, but passes throttling.
            self.assertEqual(response.status_code, 404)

        # 11th request should be throttled.
        response = self.client.post(
            self.url,
            {
                "verification_token": str(uuid.uuid4()),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 429)