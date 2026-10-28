
import hashlib
import hmac
import json

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from bookings.models import (
    Booking,
    BookingItem,
    Hold,
    Payment,
    ProcessedWebhookEvent,
)
from events.models import Event, EventSeat, Seat, TicketTier, Venue


User = get_user_model()


@override_settings(RAZORPAY_WEBHOOK_SECRET="test-webhook-secret")
class RazorpayWebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="webhook_test_user",
            password="test-password",
        )

        cls.venue = Venue.objects.create(name="Webhook Venue")

        now = timezone.now()

        cls.event = Event.objects.create(
            name="Webhook Event",
            venue=cls.venue,
            description="Testing Razorpay webhooks",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=3),
        )

        cls.seat = Seat.objects.create(
            venue=cls.venue,
            row="A",
            number="1",
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
        self.client = APIClient()

        self.booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.PAYMENT_PENDING,
            total_amount=Decimal("499.00"),
        )

        BookingItem.objects.create(
            booking=self.booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        self.hold = Hold.objects.create(
            event_seat=self.event_seat,
            user=self.user,
            booking=self.booking,
            status=Hold.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        self.payment = Payment.objects.create(
            booking=self.booking,
            provider="razorpay",
            provider_order_id="order_webhook_test_123",
            provider_payment_id="",
            idempotency_key=f"webhook_test_{self.booking.id}",
            status=Payment.Status.PENDING,
            amount=Decimal("499.00"),
        )

    def make_payload(self, event_type, payment_id="pay_webhook_123",
                     amount=49900, currency="INR"):
        return json.dumps({
            "event": event_type,
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": "order_webhook_test_123",
                        "amount": amount,
                        "currency": currency,
                    }
                }
            },
        }).encode("utf-8")

    def sign(self, payload):
        return hmac.new(
            b"test-webhook-secret",
            payload,
            hashlib.sha256,
        ).hexdigest()

    def send_event(self, payload, event_id, signature=None):
        if signature is None:
            signature = self.sign(payload)

        return self.client.post(
            "/api/bookings/payments/webhook/",
            data=payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
            HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )

    def test_captured_payment_confirms_booking(self):
        payload = self.make_payload("payment.captured")

        response = self.send_event(payload, "event_captured_1")

        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.hold.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(
            self.payment.provider_payment_id,
            "pay_webhook_123",
        )
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.hold.status, Hold.Status.CONVERTED)
        self.assertTrue(
            ProcessedWebhookEvent.objects.filter(
                event_id="event_captured_1"
            ).exists()
        )

    def test_invalid_signature_is_rejected(self):
        payload = self.make_payload("payment.captured")

        response = self.send_event(
            payload,
            "event_invalid_1",
            signature="invalid-signature",
        )

        self.assertEqual(response.status_code, 400)

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(
            self.booking.status,
            Booking.Status.PAYMENT_PENDING,
        )
        self.assertFalse(
            ProcessedWebhookEvent.objects.filter(
                event_id="event_invalid_1"
            ).exists()
        )

    def test_failed_payment_is_marked_failed(self):
        payload = self.make_payload("payment.failed")

        response = self.send_event(payload, "event_failed_1")

        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(
            self.payment.provider_payment_id,
            "pay_webhook_123",
        )
        self.assertEqual(
            self.booking.status,
            Booking.Status.PAYMENT_PENDING,
        )

    def test_duplicate_event_is_processed_only_once(self):
        payload = self.make_payload("payment.captured")

        first = self.send_event(payload, "event_duplicate_1")
        second = self.send_event(payload, "event_duplicate_1")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        self.assertEqual(
            ProcessedWebhookEvent.objects.filter(
                event_id="event_duplicate_1"
            ).count(),
            1,
        )
        self.assertEqual(Payment.objects.count(), 1)

    def test_failed_event_cannot_overwrite_successful_payment(self):
        captured_payload = self.make_payload(
            "payment.captured",
            payment_id="pay_success_123",
        )

        captured = self.send_event(
            captured_payload,
            "event_success_1",
        )
        self.assertEqual(captured.status_code, 200)

        failed_payload = self.make_payload(
            "payment.failed",
            payment_id="pay_failed_456",
        )

        failed = self.send_event(
            failed_payload,
            "event_delayed_failure_1",
        )
        self.assertEqual(failed.status_code, 200)

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(
            self.payment.provider_payment_id,
            "pay_success_123",
        )
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
