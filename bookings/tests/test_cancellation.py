from datetime import timedelta
from decimal import Decimal
import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from bookings.cancellation_policy import get_cancellation_cutoff_hours
from bookings.models import (
    Booking,
    BookingCancellation,
    BookingItem,
    ConfirmedSeat,
    Hold,
    OutboxEvent,
    Payment,
    Ticket,
)
from bookings.outbox import BOOKING_REFUND_EVENT
from bookings.services import cancel_booking, create_seat_hold, reserve_confirmed_seats
from bookings.ticket_services import TicketCheckInConflict, check_in_ticket, generate_ticket_qr
from events.models import Event, EventSeat, Seat, TicketTier, Venue

User = get_user_model()


class BookingCancellationLifecycleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="cancel_owner",
            password="test-password-123",
        )
        self.other_user = User.objects.create_user(
            username="cancel_other",
            password="test-password-123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other_user)

        self.venue = Venue.objects.create(
            name="Cancellation Venue",
            address="100 Grand Boulevard",
            city="Bengaluru",
        )
        self.event_start = timezone.now() + timedelta(days=2)
        self.event = Event.objects.create(
            name="Cancellation Test Event",
            venue=self.venue,
            description="Testing cancellation lifecycle",
            starts_at=self.event_start,
            ends_at=self.event_start + timedelta(hours=3),
        )
        self.tier = TicketTier.objects.create(
            event=self.event,
            name="Premium",
            price=Decimal("1200.00"),
        )
        self.seat_counter = 0

    def make_seat(self, event=None):
        self.seat_counter += 1
        event = self.event if event is None else event
        seat = Seat.objects.create(
            venue=self.venue,
            row="A",
            number=self.seat_counter,
        )
        return EventSeat.objects.create(
            event=event,
            seat=seat,
            ticket_tier=self.tier,
        )

    def make_booking(
        self,
        *,
        user=None,
        booking_status=Booking.Status.CONFIRMED,
        payment_status=Payment.Status.SUCCEEDED,
        ticket_status=Ticket.Status.ISSUED,
        event_starts_at=None,
        create_confirmed_seat=True,
    ):
        user = self.owner if user is None else user
        event = self.event
        if event_starts_at is not None:
            event = Event.objects.create(
                name="Custom Timing Event",
                venue=self.venue,
                description="Timing test",
                starts_at=event_starts_at,
                ends_at=event_starts_at + timedelta(hours=2),
            )

        seat = self.make_seat(event=event)
        booking = Booking.objects.create(
            user=user,
            status=booking_status,
            total_amount=Decimal("1200.00"),
        )
        item = BookingItem.objects.create(
            booking=booking,
            event_seat=seat,
            price=Decimal("1200.00"),
        )

        if booking_status in {Booking.Status.HELD, Booking.Status.PAYMENT_PENDING}:
            Hold.objects.create(
                event_seat=seat,
                user=user,
                booking=booking,
                status=Hold.Status.ACTIVE,
                expires_at=timezone.now() + timedelta(minutes=10),
            )

        if payment_status is not None:
            Payment.objects.create(
                booking=booking,
                provider="razorpay",
                provider_order_id=f"order_{booking.id}",
                provider_payment_id=f"pay_{booking.id}",
                idempotency_key=f"pay_key_{booking.id}",
                status=payment_status,
                amount=Decimal("1200.00"),
            )

        ticket = None
        if booking_status == Booking.Status.CONFIRMED:
            ticket = Ticket.objects.create(
                booking_item=item,
                ticket_number=f"TKT-{item.id}-{booking.id}",
                status=ticket_status,
            )
            generate_ticket_qr(ticket)
            if create_confirmed_seat:
                ConfirmedSeat.objects.create(
                    event_seat=seat,
                    booking_item=item,
                )

        return booking, item, ticket

    def test_valid_cancellation_of_held_booking(self):
        booking, item, _ = self.make_booking(
            booking_status=Booking.Status.HELD,
            payment_status=None,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {"reason": "Changed my mind"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

        # Hold must be cancelled
        hold = booking.holds.first()
        self.assertEqual(hold.status, Hold.Status.CANCELLED)

        # Audit record
        cancellation = BookingCancellation.objects.get(booking=booking)
        self.assertEqual(cancellation.initiator_type, BookingCancellation.Initiator.CUSTOMER)
        self.assertEqual(cancellation.user, self.owner)
        self.assertEqual(cancellation.reason, "Changed my mind")
        self.assertFalse(cancellation.refund_eligible)
        self.assertEqual(cancellation.refund_amount, Decimal("0.00"))

    def test_valid_cancellation_of_confirmed_booking_initiates_refund(self):
        booking, item, ticket = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {"reason": "Travel plan cancelled"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.REFUND_PENDING)

        # Payment is in refund pending
        payment = booking.payments.first()
        self.assertEqual(payment.status, Payment.Status.REFUND_PENDING)

        # Ticket is invalidated
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CANCELLED)

        # ConfirmedSeat allocation is freed
        self.assertFalse(ConfirmedSeat.objects.filter(booking_item=item).exists())

        # Audit record
        cancellation = BookingCancellation.objects.get(booking=booking)
        self.assertEqual(cancellation.initiator_type, BookingCancellation.Initiator.CUSTOMER)
        self.assertEqual(cancellation.user, self.owner)
        self.assertEqual(cancellation.reason, "Travel plan cancelled")
        self.assertTrue(cancellation.refund_eligible)
        self.assertEqual(cancellation.refund_amount, Decimal("1200.00"))

        # Outbox event is queued
        outbox = OutboxEvent.objects.filter(
            event_type=BOOKING_REFUND_EVENT,
            aggregate_id=payment.id,
        )
        self.assertTrue(outbox.exists())

    def test_unauthorized_cancellation_requires_authentication(self):
        booking, _, _ = self.make_booking(booking_status=Booking.Status.HELD)
        anon_client = APIClient()
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = anon_client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cancellation_of_another_users_booking_rejected(self):
        booking, _, _ = self.make_booking(
            user=self.other_user,
            booking_status=Booking.Status.CONFIRMED,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Booking not found.", str(response.data))

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_repeated_cancellation_is_idempotent(self):
        booking, _, _ = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})

        first_resp = self.client.post(url, {"reason": "Duplicate test"})
        self.assertEqual(first_resp.status_code, status.HTTP_200_OK)

        second_resp = self.client.post(url, {"reason": "Duplicate test"})
        self.assertEqual(second_resp.status_code, status.HTTP_200_OK)

        self.assertEqual(first_resp.data["status"], second_resp.data["status"])
        # Exactly one cancellation record created
        self.assertEqual(BookingCancellation.objects.filter(booking=booking).count(), 1)

    def test_cancellation_after_cutoff_is_rejected(self):
        # Event starting in 1 hour (less than 2-hour policy cutoff)
        starts_soon = timezone.now() + timedelta(hours=1)
        booking, _, _ = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            event_starts_at=starts_soon,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("within 2 hours of the event start time", str(response.data))

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_cancellation_of_used_ticket_is_rejected(self):
        booking, _, ticket = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            ticket_status=Ticket.Status.USED,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Used tickets cannot be cancelled or refunded.", str(response.data))

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_cancellation_of_refunded_booking_is_safe_and_idempotent(self):
        booking, _, _ = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        cancel_booking(user=self.owner, booking_id=booking.id)
        booking.refresh_from_db()
        booking.status = Booking.Status.REFUNDED
        booking.save()

        # Repeated cancellation after refund
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], Booking.Status.REFUNDED)

    def test_inventory_becomes_available_after_cancellation(self):
        booking, item, ticket = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        event_seat = item.event_seat

        # Before cancellation, seat is allocated and cannot be held by another user
        with self.assertRaises(ValidationError):
            create_seat_hold(
                user=self.other_user,
                event_id=self.event.id,
                event_seat_ids=[event_seat.id],
            )

        # Cancel confirmed booking
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Now, the seat can be held by another user
        new_booking = create_seat_hold(
            user=self.other_user,
            event_id=self.event.id,
            event_seat_ids=[event_seat.id],
        )
        self.assertIsNotNone(new_booking)
        self.assertEqual(new_booking.status, Booking.Status.HELD)

    def test_ticket_qr_invalidated_after_cancellation(self):
        booking, item, ticket = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        # Cancel booking
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Gate check-in with ticket QR token must fail
        staff_user = User.objects.create_user(
            username="venue_staff",
            password="staff-password",
            is_staff=True,
        )
        with self.assertRaises(TicketCheckInConflict) as cm:
            check_in_ticket(
                verification_token=ticket.verification_token,
            )
        self.assertIn("Ticket has been cancelled", str(cm.exception))

    def test_cancellation_during_payment_pending_cancels_hold(self):
        booking, item, _ = self.make_booking(
            booking_status=Booking.Status.PAYMENT_PENDING,
            payment_status=Payment.Status.PENDING,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        hold = booking.holds.first()
        self.assertEqual(hold.status, Hold.Status.CANCELLED)

    def test_refund_eligibility_and_precise_decimal_calculation(self):
        booking, item, _ = self.make_booking(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.SUCCEEDED,
        )
        url = reverse("booking-cancel", kwargs={"pk": booking.id})
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cancellation = BookingCancellation.objects.get(booking=booking)
        self.assertIsInstance(cancellation.refund_amount, Decimal)
        self.assertEqual(cancellation.refund_amount, Decimal("1200.00"))
