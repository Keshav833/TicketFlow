import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import Booking, BookingItem, Payment, ProcessedWebhookEvent, Refund
from bookings.outbox import create_booking_refund_outbox
from bookings.refund_services import (
    apply_provider_refund_update,
    create_refund_request,
    reconcile_refund,
)
from bookings.tasks import refund_late_payment
from bookings.webhook_services import process_razorpay_webhook
from events.models import Event, EventSeat, Seat, TicketTier, Venue


User = get_user_model()


@override_settings(RAZORPAY_WEBHOOK_SECRET="refund-webhook-secret")
class RefundLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="refund_owner", password="pass-12345")
        venue = Venue.objects.create(name="Refund venue", address="1 Road", city="Delhi")
        starts_at = timezone.now() + timedelta(days=3)
        event = Event.objects.create(
            name="Refund event", venue=venue, description="Refund test",
            starts_at=starts_at, ends_at=starts_at + timedelta(hours=2),
        )
        tier = TicketTier.objects.create(event=event, name="Standard", price=Decimal("100.00"))
        seat = Seat.objects.create(venue=venue, row="A", number=1)
        event_seat = EventSeat.objects.create(event=event, seat=seat, ticket_tier=tier)
        self.booking = Booking.objects.create(
            user=self.user, status=Booking.Status.REFUND_PENDING, total_amount=Decimal("100.00"),
        )
        BookingItem.objects.create(booking=self.booking, event_seat=event_seat, price=Decimal("100.00"))
        self.payment = Payment.objects.create(
            booking=self.booking, provider="razorpay", provider_order_id="order_refund_1",
            provider_payment_id="pay_refund_1", idempotency_key="payment_refund_1",
            amount=Decimal("100.00"), status=Payment.Status.REFUND_PENDING,
        )

    def request(self, amount, key="refund-key-1"):
        return create_refund_request(payment=self.payment, amount=Decimal(amount), idempotency_key=key)

    def entity(self, refund, *, status="processed", created_at=100):
        return {
            "id": f"rfnd_{refund.id}", "payment_id": self.payment.provider_payment_id,
            "amount": int(refund.amount * 100), "currency": "INR", "status": status,
            "created_at": created_at, "notes": {"ticketflow_refund_key": refund.idempotency_key},
        }

    def signed_refund_event(self, refund, event_type, event_id, *, created_at=100):
        payload = json.dumps({"event": event_type, "payload": {"refund": {"entity": self.entity(refund, status=event_type.split(".")[1], created_at=created_at)}}}).encode()
        signature = hmac.new(b"refund-webhook-secret", payload, hashlib.sha256).hexdigest()
        return process_razorpay_webhook(payload=payload, signature=signature, event_id=event_id)

    def test_request_is_idempotent_and_never_exceeds_captured_balance(self):
        refund = self.request("40.00")
        self.assertEqual(refund, self.request("40.00"))
        with self.assertRaises(ValidationError):
            self.request("60.01", "another-refund")
        second = self.request("60.00", "second-refund")
        self.assertEqual(second.amount, Decimal("60.00"))

    def test_uncaptured_payment_cannot_be_refunded(self):
        self.payment.status = Payment.Status.PENDING
        self.payment.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            self.request("1.00")

    @patch("bookings.payment_services.get_razorpay_client")
    def test_provider_acceptance_is_submitted_not_financial_completion(self, get_client):
        refund = self.request("100.00")
        event = create_booking_refund_outbox(self.payment, refund=refund)
        get_client.return_value.payment.refund.return_value = self.entity(refund, status="processed")

        result = refund_late_payment.run(event.id)

        refund.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(result["status"], Refund.Status.SUBMITTED)
        self.assertEqual(refund.status, Refund.Status.SUBMITTED)
        self.assertEqual(self.booking.status, Booking.Status.REFUND_PENDING)

    def test_processed_webhook_confirms_refund_and_duplicate_is_safe(self):
        refund = self.request("100.00")
        apply_provider_refund_update(refund_id=refund.id, entity=self.entity(refund, status="pending"))
        self.signed_refund_event(refund, "refund.processed", "refund-event-1")
        self.signed_refund_event(refund, "refund.processed", "refund-event-1")

        refund.refresh_from_db()
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PROCESSED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.booking.status, Booking.Status.REFUNDED)
        self.assertEqual(ProcessedWebhookEvent.objects.filter(event_id="refund-event-1").count(), 1)

    def test_processed_webhook_wins_over_out_of_order_failure(self):
        refund = self.request("100.00")
        apply_provider_refund_update(refund_id=refund.id, entity=self.entity(refund, status="pending"))
        self.signed_refund_event(refund, "refund.processed", "refund-processed", created_at=200)
        self.signed_refund_event(refund, "refund.failed", "refund-failed-old", created_at=100)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PROCESSED)

    def test_partial_refunds_only_complete_payment_after_full_amount(self):
        first = self.request("40.00", "partial-1")
        second = self.request("60.00", "partial-2")
        apply_provider_refund_update(refund_id=first.id, entity=self.entity(first))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUND_PENDING)
        apply_provider_refund_update(refund_id=second.id, entity=self.entity(second))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)

    @patch("bookings.payment_services.get_razorpay_client")
    def test_timeout_is_reconciled_without_resubmitting(self, get_client):
        refund = self.request("100.00")
        event = create_booking_refund_outbox(self.payment, refund=refund)
        get_client.return_value.payment.refund.side_effect = TimeoutError("provider timeout")

        with self.assertRaises(TimeoutError):
            refund_late_payment.run(event.id)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.SUBMITTED)

        get_client.return_value.payment.all_refunds.return_value = {"items": [self.entity(refund)]}
        reconcile_refund(refund.id)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PROCESSED)

    def test_failed_refund_is_recorded_without_marking_booking_refunded(self):
        refund = self.request("100.00")
        apply_provider_refund_update(refund_id=refund.id, entity=self.entity(refund, status="failed"))
        refund.refresh_from_db()
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.FAILED)
        self.assertEqual(self.payment.status, Payment.Status.REFUND_PENDING)
        self.assertEqual(self.booking.status, Booking.Status.REFUND_PENDING)
