from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import (
    Booking,
    BookingEmailDelivery,
    BookingItem,
    OutboxEvent,
    Payment,
    Ticket,
)
from bookings.outbox import create_booking_fulfillment_outbox
from bookings.tasks import (
    dispatch_pending_outbox_events,
    fulfill_confirmed_booking,
    recover_stale_email_deliveries,
    recover_stale_outbox_events,
    refund_late_payment,
    send_booking_confirmation_email_task,
)
from events.models import Event, EventSeat, Seat, TicketTier, Venue


User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class BookingCeleryTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="celery_task_test_user",
            password="test-password",
            email="celery@example.com",
        )
        cls.venue = Venue.objects.create(name="Celery Test Venue")
        starts_at = timezone.now() + timedelta(days=1)
        cls.event = Event.objects.create(
            name="Celery Test Event",
            venue=cls.venue,
            description="Testing asynchronous booking fulfillment",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
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
        self.item = BookingItem.objects.create(
            booking=self.booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )
        self.payment = Payment.objects.create(
            booking=self.booking,
            provider="razorpay",
            provider_order_id=f"order_celery_{self.booking.id}",
            provider_payment_id=f"payment_celery_{self.booking.id}",
            idempotency_key=f"celery_test_{self.booking.id}",
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("499.00"),
        )
        self.outbox_event = create_booking_fulfillment_outbox(self.booking)

    def test_duplicate_fulfillment_delivery_creates_one_ticket_and_email(self):
        with patch("bookings.tasks.send_booking_confirmation_email", return_value=1) as send_email:
            first = fulfill_confirmed_booking.apply(
                args=(self.outbox_event.id,),
                throw=True,
            ).get()
            duplicate = fulfill_confirmed_booking.apply(
                args=(self.outbox_event.id,),
                throw=True,
            ).get()

        self.assertEqual(first["status"], "fulfilled")
        self.assertEqual(duplicate["status"], "already_completed")
        self.assertEqual(
            Ticket.objects.filter(booking_item__booking=self.booking).count(),
            1,
        )
        self.assertEqual(send_email.call_count, 1)
        self.outbox_event.refresh_from_db()
        self.assertEqual(self.outbox_event.status, OutboxEvent.Status.COMPLETED)

    def test_failed_fulfillment_is_recorded_and_retried_from_outbox(self):
        with patch("bookings.tasks.generate_tickets", side_effect=RuntimeError("storage unavailable")):
            with self.assertRaises(RuntimeError):
                fulfill_confirmed_booking.apply(
                    args=(self.outbox_event.id,),
                    throw=True,
                )

        self.outbox_event.refresh_from_db()
        self.assertEqual(self.outbox_event.status, OutboxEvent.Status.FAILED)
        self.assertIn("storage unavailable", self.outbox_event.last_error)

        OutboxEvent.objects.filter(pk=self.outbox_event.pk).update(
            available_at=timezone.now()
        )
        with patch("bookings.tasks.send_booking_confirmation_email", return_value=1):
            dispatch_pending_outbox_events.apply(throw=True)

        self.outbox_event.refresh_from_db()
        self.assertEqual(self.outbox_event.status, OutboxEvent.Status.COMPLETED)
        self.assertEqual(
            Ticket.objects.filter(booking_item__booking=self.booking).count(),
            1,
        )

    def test_email_task_retries_and_ignores_duplicate_after_success(self):
        with patch(
            "bookings.tasks.send_booking_confirmation_email",
            side_effect=[RuntimeError("temporary mail error"), 1],
        ) as send_email:
            first = send_booking_confirmation_email_task.apply(
                args=(self.booking.id,),
                throw=False,
            ).get()
            duplicate = send_booking_confirmation_email_task.apply(
                args=(self.booking.id,),
                throw=True,
            ).get()

        self.assertEqual(first["status"], "sent")
        self.assertEqual(duplicate["status"], "already_sent")
        self.assertEqual(send_email.call_count, 2)
        delivery = BookingEmailDelivery.objects.get(booking=self.booking)
        self.assertEqual(delivery.status, BookingEmailDelivery.Status.SENT)
        self.assertEqual(delivery.attempts, 2)

    def test_stale_dispatched_event_is_requeued(self):
        OutboxEvent.objects.filter(pk=self.outbox_event.pk).update(
            status=OutboxEvent.Status.DISPATCHED,
            locked_at=timezone.now() - timedelta(minutes=11),
        )

        recovered = recover_stale_outbox_events.apply(throw=True).get()

        self.assertEqual(recovered, 1)
        self.outbox_event.refresh_from_db()
        self.assertEqual(self.outbox_event.status, OutboxEvent.Status.PENDING)
        self.assertIsNone(self.outbox_event.locked_at)

    def test_broker_failure_leaves_event_available_for_later_dispatch(self):
        with patch(
            "bookings.tasks.fulfill_confirmed_booking.delay",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            with self.assertRaises(ConnectionError):
                dispatch_pending_outbox_events.apply(throw=True)

        self.outbox_event.refresh_from_db()
        self.assertEqual(self.outbox_event.status, OutboxEvent.Status.FAILED)
        self.assertIn("Redis unavailable", self.outbox_event.last_error)

    def test_stale_email_delivery_is_reset_and_requeued(self):
        delivery = BookingEmailDelivery.objects.create(
            booking=self.booking,
            status=BookingEmailDelivery.Status.PROCESSING,
            locked_at=timezone.now() - timedelta(minutes=16),
        )

        with patch("bookings.tasks.send_booking_confirmation_email_task.delay") as enqueue:
            result = recover_stale_email_deliveries.apply(throw=True).get()

        delivery.refresh_from_db()
        self.assertEqual(result, {"queued": 1, "recovered": 1})
        self.assertEqual(delivery.status, BookingEmailDelivery.Status.PENDING)
        self.assertIsNone(delivery.locked_at)
        enqueue.assert_called_once_with(self.booking.id)

    @patch("bookings.payment_services.get_razorpay_client")
    def test_late_payment_refund_is_submitted_pending_provider_confirmation(self, mock_get_client):
        expired_booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.EXPIRED,
            total_amount=Decimal("499.00"),
        )
        late_payment = Payment.objects.create(
            booking=expired_booking,
            provider="razorpay",
            provider_order_id="order_late_refund",
            provider_payment_id="pay_late_refund",
            idempotency_key="late-refund-payment",
            status=Payment.Status.REFUND_PENDING,
            amount=Decimal("499.00"),
        )
        refund_event = OutboxEvent.objects.create(
            event_type="late_payment_refund",
            aggregate_id=late_payment.id,
            idempotency_key=f"late_payment_refund:{late_payment.id}",
            status=OutboxEvent.Status.DISPATCHED,
        )
        mock_get_client.return_value.payment.refund.return_value = {
            "id": "rfnd_late_payment",
        }

        result = refund_late_payment.apply(
            args=(refund_event.id,),
            throw=True,
        ).get()

        late_payment.refresh_from_db()
        refund_event.refresh_from_db()
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(late_payment.status, Payment.Status.REFUND_PENDING)
        self.assertEqual(late_payment.provider_refund_id, "rfnd_late_payment")
        self.assertEqual(refund_event.status, OutboxEvent.Status.COMPLETED)
        mock_get_client.return_value.payment.refund.assert_called_once_with(
            "pay_late_refund",
            {
                "amount": 49900,
                "notes": {"ticketflow_refund_key": f"late-payment:{late_payment.id}"},
            },
        )
