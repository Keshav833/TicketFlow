import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, BookingItem, Payment, Ticket
from bookings.ticket_services import generate_ticket_qr
from events.models import Event, EventSeat, Seat, TicketTier, Venue


User = get_user_model()


class CustomerTicketAPITests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.owner = User.objects.create_user(
            username="ticket_owner",
            password="test-password-123",
        )
        self.other = User.objects.create_user(
            username="ticket_other",
            password="test-password-123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)

        self.venue = Venue.objects.create(
            name="Customer Ticket Venue",
            address="1 Ticket Street",
            city="Mumbai",
        )
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(
            name="Customer Ticket Event",
            venue=self.venue,
            description="Customer ticket API",
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )
        self.tier = TicketTier.objects.create(
            event=self.event,
            name="Standard",
            price=Decimal("750.00"),
        )
        self.seat_number = 0

    def make_seat(self):
        self.seat_number += 1
        seat = Seat.objects.create(
            venue=self.venue,
            row="C",
            number=self.seat_number,
        )
        return EventSeat.objects.create(
            event=self.event,
            seat=seat,
            ticket_tier=self.tier,
        )

    def make_ticket(
        self,
        *,
        user=None,
        booking_status=Booking.Status.CONFIRMED,
        payment_status=Payment.Status.SUCCEEDED,
        ticket_status=Ticket.Status.ISSUED,
        with_qr=False,
        create_payment=True,
    ):
        user = self.owner if user is None else user
        booking = Booking.objects.create(
            user=user,
            status=booking_status,
            total_amount=Decimal("750.00"),
        )
        item = BookingItem.objects.create(
            booking=booking,
            event_seat=self.make_seat(),
            price=Decimal("750.00"),
        )
        if create_payment:
            Payment.objects.create(
                booking=booking,
                provider="razorpay",
                provider_order_id=f"order_{booking.id}",
                provider_payment_id=f"pay_{booking.id}",
                idempotency_key=f"booking_{booking.id}_razorpay",
                status=payment_status,
                amount=Decimal("750.00"),
            )
        ticket = Ticket.objects.create(
            booking_item=item,
            ticket_number=f"TKT-{item.id}-{booking.id}",
            status=ticket_status,
        )
        if with_qr:
            generate_ticket_qr(ticket)
            ticket.refresh_from_db()
        return booking, ticket

    def test_authenticated_customer_lists_only_confirmed_paid_tickets(self):
        _, visible = self.make_ticket(with_qr=True)
        self.make_ticket(
            booking_status=Booking.Status.PAYMENT_PENDING,
            payment_status=Payment.Status.PENDING,
        )

        response = self.client.get(reverse("customer-ticket-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        ticket_data = response.data["results"][0]
        self.assertEqual(ticket_data["id"], visible.id)
        self.assertEqual(ticket_data["ticket_number"], visible.ticket_number)
        self.assertEqual(ticket_data["status"], Ticket.Status.ISSUED)
        self.assertEqual(ticket_data["event_name"], self.event.name)
        self.assertEqual(ticket_data["venue_name"], self.venue.name)
        self.assertEqual(ticket_data["venue_city"], self.venue.city)
        self.assertEqual(ticket_data["seat_row"], "C")
        self.assertEqual(ticket_data["seat_number"], 1)
        self.assertEqual(ticket_data["booking_id"], visible.booking_item.booking_id)
        self.assertTrue(ticket_data["qr_available"])
        self.assertNotIn("verification_token", ticket_data)
        self.assertNotIn("qr_code", ticket_data)

    def test_empty_ticket_list(self):
        response = self.client.get(reverse("customer-ticket-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_customer_cannot_see_another_customers_tickets(self):
        _, own = self.make_ticket()
        _, foreign = self.make_ticket(user=self.other)

        response = self.client.get(reverse("customer-ticket-list"))

        self.assertEqual(response.status_code, 200)
        returned_ids = [ticket["id"] for ticket in response.data["results"]]
        self.assertEqual(returned_ids, [own.id])
        self.assertNotIn(foreign.id, returned_ids)

    def test_customer_cannot_access_another_customers_ticket(self):
        _, foreign = self.make_ticket(user=self.other, with_qr=True)

        detail = self.client.get(
            reverse("customer-ticket-detail", args=[foreign.id])
        )
        qr = self.client.get(reverse("customer-ticket-qr", args=[foreign.id]))
        download = self.client.get(
            reverse("customer-ticket-download", args=[foreign.id])
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(qr.status_code, 404)
        self.assertEqual(download.status_code, 404)
        self.assertEqual(self.other_client.get(
            reverse("customer-ticket-detail", args=[foreign.id])
        ).status_code, 200)

    def test_ticket_details(self):
        _, ticket = self.make_ticket()

        response = self.client.get(
            reverse("customer-ticket-detail", args=[ticket.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["ticket_number"], ticket.ticket_number)
        self.assertEqual(response.data["booking_status"], Booking.Status.CONFIRMED)
        self.assertEqual(response.data["price"], "750.00")
        self.assertEqual(response.data["tier_name"], "Standard")
        self.assertFalse(response.data["qr_available"])
        self.assertNotIn("verification_token", response.data)

    def test_qr_retrieval_returns_the_stored_image(self):
        _, ticket = self.make_ticket(with_qr=True)
        with ticket.qr_code.open("rb") as stored_file:
            stored = stored_file.read()

        response = self.client.get(reverse("customer-ticket-qr", args=[ticket.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, stored)
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_missing_qr_file_is_rejected(self):
        _, ticket = self.make_ticket()

        response = self.client.get(reverse("customer-ticket-qr", args=[ticket.id]))

        self.assertEqual(response.status_code, 404)
        self.assertIn("QR image", response.data["message"])

    def test_unsafe_qr_path_is_rejected(self):
        _, ticket = self.make_ticket()
        ticket.qr_code.name = "tickets/qr_codes/../../secret.png"
        ticket.save(update_fields=["qr_code"])

        response = self.client.get(reverse("customer-ticket-qr", args=[ticket.id]))

        self.assertEqual(response.status_code, 404)

    def test_ticket_download(self):
        _, ticket = self.make_ticket()

        response = self.client.get(
            reverse("customer-ticket-download", args=[ticket.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            f'filename="{ticket.ticket_number}.pdf"',
            response["Content-Disposition"],
        )
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(ticket.ticket_number.encode(), response.content)
        self.assertIn(b"Customer Ticket Event", response.content)
        self.assertNotIn(str(ticket.verification_token).encode(), response.content)

    def test_pending_booking_tickets_are_hidden(self):
        _, ticket = self.make_ticket(
            booking_status=Booking.Status.PAYMENT_PENDING,
            payment_status=Payment.Status.PENDING,
            with_qr=True,
        )

        self.assertEqual(self.client.get(reverse("customer-ticket-list")).data["count"], 0)
        self.assertEqual(
            self.client.get(reverse("customer-ticket-detail", args=[ticket.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("customer-ticket-qr", args=[ticket.id])).status_code,
            404,
        )

    def test_failed_payment_tickets_are_hidden(self):
        _, pending = self.make_ticket(
            booking_status=Booking.Status.PAYMENT_PENDING,
            payment_status=Payment.Status.FAILED,
        )
        _, confirmed_without_capture = self.make_ticket(
            booking_status=Booking.Status.CONFIRMED,
            payment_status=Payment.Status.FAILED,
        )

        response = self.client.get(reverse("customer-ticket-list"))
        returned_ids = [ticket["id"] for ticket in response.data["results"]]

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(pending.id, returned_ids)
        self.assertNotIn(confirmed_without_capture.id, returned_ids)
        self.assertEqual(
            self.client.get(
                reverse("customer-ticket-detail", args=[confirmed_without_capture.id])
            ).status_code,
            404,
        )

    def test_expired_booking_tickets_are_hidden(self):
        _, ticket = self.make_ticket(
            booking_status=Booking.Status.EXPIRED,
            create_payment=False,
        )

        self.assertEqual(
            self.client.get(reverse("customer-ticket-detail", args=[ticket.id])).status_code,
            404,
        )

    def test_confirmed_booking_ticket_is_visible(self):
        _, ticket = self.make_ticket()

        response = self.client.get(
            reverse("customer-ticket-detail", args=[ticket.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Ticket.Status.ISSUED)
        self.assertEqual(response.data["booking_status"], Booking.Status.CONFIRMED)

    def test_cancelled_and_refunded_bookings_hide_tickets(self):
        _, cancelled = self.make_ticket(booking_status=Booking.Status.CANCELLED)
        _, refunded = self.make_ticket(booking_status=Booking.Status.REFUNDED)
        _, refund_pending = self.make_ticket(
            booking_status=Booking.Status.REFUND_PENDING,
            payment_status=Payment.Status.REFUND_PENDING,
        )

        response = self.client.get(reverse("customer-ticket-list"))
        self.assertEqual(response.data["count"], 0)
        for ticket in (cancelled, refunded, refund_pending):
            self.assertEqual(
                self.client.get(
                    reverse("customer-ticket-detail", args=[ticket.id])
                ).status_code,
                404,
            )

    def test_cancelled_ticket_on_confirmed_booking_is_visible_but_not_downloadable(self):
        _, ticket = self.make_ticket(
            ticket_status=Ticket.Status.CANCELLED,
            with_qr=True,
        )

        detail = self.client.get(reverse("customer-ticket-detail", args=[ticket.id]))
        qr = self.client.get(reverse("customer-ticket-qr", args=[ticket.id]))
        download = self.client.get(
            reverse("customer-ticket-download", args=[ticket.id])
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], Ticket.Status.CANCELLED)
        self.assertEqual(qr.status_code, 409)
        self.assertEqual(download.status_code, 409)

    def test_used_ticket_remains_downloadable(self):
        _, ticket = self.make_ticket(
            ticket_status=Ticket.Status.USED,
            with_qr=True,
        )

        detail = self.client.get(reverse("customer-ticket-detail", args=[ticket.id]))
        qr = self.client.get(reverse("customer-ticket-qr", args=[ticket.id]))

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], Ticket.Status.USED)
        self.assertIsNotNone(detail.data["issued_at"])
        self.assertEqual(qr.status_code, 200)

    def test_unauthenticated_access_is_rejected(self):
        _, ticket = self.make_ticket(with_qr=True)
        anonymous = APIClient()

        for url in (
            reverse("customer-ticket-list"),
            reverse("customer-ticket-detail", args=[ticket.id]),
            reverse("customer-ticket-qr", args=[ticket.id]),
            reverse("customer-ticket-download", args=[ticket.id]),
        ):
            self.assertEqual(anonymous.get(url).status_code, 401)

    def test_ticket_list_does_not_query_per_ticket(self):
        self.make_ticket(with_qr=True)
        self.make_ticket(with_qr=True)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("customer-ticket-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertLessEqual(len(queries), 3)
