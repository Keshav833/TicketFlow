
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.payment_services import create_razorpay_order
from bookings.payment_services import verify_razorpay_payment
from bookings.models import Booking, BookingItem, Hold, Payment
from events.models import Venue, Event, Seat, TicketTier, EventSeat


User = get_user_model()


class PaymentRetryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="payment_test_user",
            password="test-password-123",
        )

        cls.venue = Venue.objects.create(
            name="Payment Test Venue",
            address="123 Test Street",
            city="Test City",
        )

        start = timezone.now() + timedelta(days=1)

        cls.event = Event.objects.create(
            name="Payment Test Event",
            venue=cls.venue,
            description="Payment retry test",
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

    def create_pending_payment(self):
        booking = Booking.objects.create(
            user=self.user,
            status=Booking.Status.PAYMENT_PENDING,
            total_amount=Decimal("499.00"),
        )

        BookingItem.objects.create(
            booking=booking,
            event_seat=self.event_seat,
            price=Decimal("499.00"),
        )

        Hold.objects.create(
            event_seat=self.event_seat,
            user=self.user,
            booking=booking,
            status=Hold.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        payment = Payment.objects.create(
            booking=booking,
            provider="razorpay",
            provider_order_id="order_existing_test_123",
            provider_payment_id="",
            idempotency_key=f"booking_{booking.id}_razorpay",
            status=Payment.Status.PENDING,
            amount=Decimal("499.00"),
        )

        return booking, payment

    @patch("bookings.payment_services.get_razorpay_client")
    def test_existing_pending_order_is_reused(self, mock_get_client):
        booking, payment = self.create_pending_payment()

        result = create_razorpay_order(
            user=self.user,
            booking_id=booking.id,
        )

        self.assertEqual(result["booking_id"], booking.id)
        self.assertEqual(result["payment_id"], payment.id)
        self.assertEqual(
            result["razorpay_order_id"],
            "order_existing_test_123",
        )
        self.assertEqual(result["amount"], 49900)

        # A reusable order must not require another Razorpay API call.
        mock_get_client.assert_not_called()

        self.assertEqual(
            Payment.objects.filter(booking=booking).count(),
            1,
        )



    @patch("bookings.payment_services.get_razorpay_client")
    def test_razorpay_failure_does_not_create_duplicate_payment(
        self, mock_get_client
    ):
        booking, payment = self.create_pending_payment()

        # Simulate Razorpay being unavailable.
        mock_get_client.side_effect = RuntimeError(
            "Simulated Razorpay outage"
        )

        result = create_razorpay_order(
            user=self.user,
            booking_id=booking.id,
        )

        # The existing order should be reused without contacting Razorpay.
        self.assertEqual(result["payment_id"], payment.id)
        mock_get_client.assert_not_called()

        self.assertEqual(
            Payment.objects.filter(booking=booking).count(),
            1,
        )


    @patch("bookings.payment_services.get_razorpay_client")
    def test_razorpay_failure_returns_error_without_duplicate_payment(
        self, mock_get_client
    ):
        booking, payment = self.create_pending_payment()

        # Simulate a pending payment record with no Razorpay order yet.
        payment.provider_order_id = ""
        payment.save(update_fields=["provider_order_id"])

        mock_get_client.return_value.order.create.side_effect = RuntimeError(
            "Simulated Razorpay outage"
        )

        with self.assertRaises(Exception):
            create_razorpay_order(
                user=self.user,
                booking_id=booking.id,
            )

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_order_id, "")
        self.assertEqual(
            Payment.objects.filter(booking=booking).count(),
            1,
        )

        booking.refresh_from_db()
        self.assertEqual(
            booking.status,
            Booking.Status.PAYMENT_PENDING,
        )

        
    @patch("bookings.payment_services.get_razorpay_client")
    def test_failed_order_creation_is_not_retried_blindly(
        self, mock_get_client
    ):
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

        Hold.objects.create(
            event_seat=self.event_seat,
            user=self.user,
            booking=booking,
            status=Hold.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        mock_client = mock_get_client.return_value
        mock_client.order.create.side_effect = RuntimeError(
            "Simulated Razorpay timeout"
        )

        # First attempt reaches Razorpay and fails.
        with self.assertRaises(ValidationError):
            create_razorpay_order(
                user=self.user,
                booking_id=booking.id,
            )

        payment = Payment.objects.get(booking=booking)

        self.assertEqual(payment.status, Payment.Status.CREATING)
        self.assertEqual(payment.provider_order_id, "")
        mock_client.order.create.assert_called_once()

        # Record the call count after the first attempt.
        calls_before_retry = mock_client.order.create.call_count
        self.assertEqual(calls_before_retry, 1)

        # Second attempt must not contact Razorpay again.
        with self.assertRaises(ValidationError):
            create_razorpay_order(
                user=self.user,
                booking_id=booking.id,
            )

        self.assertEqual(
            mock_client.order.create.call_count,
            calls_before_retry,
        )


        
    @patch("bookings.payment_services.get_razorpay_client")
    def test_valid_captured_payment_confirms_booking_and_converts_hold(
        self, mock_get_client
    ):
        booking, payment = self.create_pending_payment()

        mock_client = mock_get_client.return_value
        mock_client.payment.fetch.return_value = {
            "id": "pay_test_123",
            "order_id": payment.provider_order_id,
            "amount": 49900,
            "currency": "INR",
            "status": "captured",
        }

        result = verify_razorpay_payment(
            user=self.user,
            booking_id=booking.id,
            razorpay_order_id=payment.provider_order_id,
            razorpay_payment_id="pay_test_123",
            razorpay_signature="valid_test_signature",
        )

        mock_client.utility.verify_payment_signature.assert_called_once_with({
            "razorpay_order_id": payment.provider_order_id,
            "razorpay_payment_id": "pay_test_123",
            "razorpay_signature": "valid_test_signature",
        })

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.provider_payment_id, "pay_test_123")
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(
            booking.holds.get().status,
            Hold.Status.CONVERTED,
        )
        self.assertEqual(result["booking_status"], Booking.Status.CONFIRMED)


    @patch("bookings.payment_services.get_razorpay_client")
    def test_invalid_signature_does_not_confirm_booking(self, mock_get_client):
        booking, payment = self.create_pending_payment()

        mock_client = mock_get_client.return_value

        import razorpay
        mock_client.utility.verify_payment_signature.side_effect = (
            razorpay.errors.SignatureVerificationError(
                "Invalid signature",
                "invalid_signature",
            )
        )

        with self.assertRaises(ValidationError):
            verify_razorpay_payment(
                user=self.user,
                booking_id=booking.id,
                razorpay_order_id=payment.provider_order_id,
                razorpay_payment_id="pay_fake_123",
                razorpay_signature="invalid_signature",
            )

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(booking.status, Booking.Status.PAYMENT_PENDING)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_payment_id, "")

        mock_client.payment.fetch.assert_not_called()



    @patch("bookings.payment_services.get_razorpay_client")
    def test_amount_mismatch_does_not_confirm_booking(self, mock_get_client):
        booking, payment = self.create_pending_payment()

        mock_client = mock_get_client.return_value
        mock_client.payment.fetch.return_value = {
            "id": "pay_test_mismatch",
            "order_id": payment.provider_order_id,
            "amount": 10000,
            "currency": "INR",
            "status": "captured",
        }

        with self.assertRaises(ValidationError):
            verify_razorpay_payment(
                user=self.user,
                booking_id=booking.id,
                razorpay_order_id=payment.provider_order_id,
                razorpay_payment_id="pay_test_mismatch",
                razorpay_signature="valid_test_signature",
            )

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(booking.status, Booking.Status.PAYMENT_PENDING)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_payment_id, "")



    @patch("bookings.payment_services.get_razorpay_client")
    def test_uncaptured_payment_does_not_confirm_booking(self, mock_get_client):
        booking, payment = self.create_pending_payment()

        mock_client = mock_get_client.return_value
        mock_client.payment.fetch.return_value = {
            "id": "pay_test_authorized",
            "order_id": payment.provider_order_id,
            "amount": 49900,
            "currency": "INR",
            "status": "authorized",
        }

        with self.assertRaises(ValidationError):
            verify_razorpay_payment(
                user=self.user,
                booking_id=booking.id,
                razorpay_order_id=payment.provider_order_id,
                razorpay_payment_id="pay_test_authorized",
                razorpay_signature="valid_test_signature",
            )

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(booking.status, Booking.Status.PAYMENT_PENDING)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_payment_id, "")



    @patch("bookings.payment_services.get_razorpay_client")
    def test_repeated_verification_does_not_duplicate_state_changes(
        self, mock_get_client
    ):
        booking, payment = self.create_pending_payment()

        mock_client = mock_get_client.return_value
        mock_client.payment.fetch.return_value = {
            "id": "pay_test_duplicate",
            "order_id": payment.provider_order_id,
            "amount": 49900,
            "currency": "INR",
            "status": "captured",
        }

        kwargs = {
            "user": self.user,
            "booking_id": booking.id,
            "razorpay_order_id": payment.provider_order_id,
            "razorpay_payment_id": "pay_test_duplicate",
            "razorpay_signature": "valid_test_signature",
        }

        first_result = verify_razorpay_payment(**kwargs)
        second_result = verify_razorpay_payment(**kwargs)

        self.assertEqual(
            first_result["payment_status"],
            Payment.Status.SUCCEEDED,
        )
        self.assertEqual(
            second_result["detail"],
            "Payment already verified.",
        )

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.provider_payment_id, "pay_test_duplicate")
        self.assertEqual(Payment.objects.filter(booking=booking).count(), 1)

        # The second request should return early without contacting Razorpay.
        mock_client.utility.verify_payment_signature.assert_called_once()
        mock_client.payment.fetch.assert_called_once()
