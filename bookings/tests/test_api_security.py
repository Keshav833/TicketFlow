import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, BookingItem, Hold
from events.models import Event, EventSeat, Seat, TicketTier, Venue
from users.models import User


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def booking_inventory(db):
    user = User.objects.create_user(
        username="api_security_user",
        password="a-strong-password-123",
    )
    venue = Venue.objects.create(
        name="Security Test Venue",
        address="Test Address",
        city="Test City",
    )
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        name="Security Test Event",
        venue=venue,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
    )
    tier = TicketTier.objects.create(
        event=event,
        name="Standard",
        price="500.00",
    )
    seat = Seat.objects.create(venue=venue, row="A", number=1)
    event_seat = EventSeat.objects.create(
        event=event,
        seat=seat,
        ticket_tier=tier,
    )
    return user, event, event_seat


@pytest.mark.django_db
def test_seat_hold_endpoint_is_throttled(booking_inventory):
    user, event, event_seat = booking_inventory
    another_user = User.objects.create_user(
        username="api_security_another_user",
        password="a-strong-password-123",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    created = client.post(
        "/api/bookings/holds/",
        {
            "event_id": event.id,
            "event_seat_ids": [event_seat.id],
        },
        format="json",
    )
    assert created.status_code == 201
    for _ in range(9):
        response = client.post("/api/bookings/holds/", {}, format="json")
        assert response.status_code == 400
    throttled = client.post("/api/bookings/holds/", {}, format="json")
    assert throttled.status_code == 429

    another_client = APIClient()
    another_client.force_authenticate(user=another_user)
    assert another_client.post(
        "/api/bookings/holds/",
        {},
        format="json",
    ).status_code == 400


@pytest.mark.django_db
def test_payment_order_endpoint_is_throttled(booking_inventory, monkeypatch):
    user, _, _ = booking_inventory
    client = APIClient()
    client.force_authenticate(user=user)
    monkeypatch.setattr(
        "bookings.views.create_razorpay_order",
        lambda **kwargs: {
            "booking_id": 1,
            "payment_id": 1,
            "razorpay_order_id": "order_test",
            "razorpay_key_id": "test-key",
            "amount": 50000,
            "currency": "INR",
        },
    )

    for _ in range(5):
        response = client.post(
            "/api/bookings/payments/create-order/",
            {"booking_id": 1},
            format="json",
        )
        assert response.status_code == 201
    throttled = client.post(
        "/api/bookings/payments/create-order/",
        {"booking_id": 1},
        format="json",
    )
    assert throttled.status_code == 429


@pytest.mark.django_db
def test_invalid_payment_verification_uses_standard_validation_response(
    booking_inventory,
):
    user, _, _ = booking_inventory
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/bookings/payments/verify/",
        {
            "booking_id": "not-an-id",
            "razorpay_order_id": "",
            "razorpay_payment_id": "payment-id",
            "razorpay_signature": "short",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["success"] is False
    assert response.data["message"] == "Validation failed."
    assert "errors" in response.data


@pytest.mark.django_db
def test_payment_and_booking_fields_cannot_be_set_by_hold_request(booking_inventory):
    user, event, event_seat = booking_inventory
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/bookings/holds/",
        {
            "event_id": event.id,
            "event_seat_ids": [event_seat.id],
            "user_id": 999999,
            "status": Booking.Status.CONFIRMED,
            "total_amount": "0.01",
        },
        format="json",
    )

    assert response.status_code == 201
    booking = Booking.objects.get(pk=response.data["id"])
    assert booking.user_id == user.id
    assert booking.status == Booking.Status.HELD
    assert booking.total_amount == Decimal("500.00")
    assert BookingItem.objects.filter(booking=booking).count() == 1
    assert Hold.objects.filter(booking=booking, status=Hold.Status.ACTIVE).exists()


@pytest.mark.django_db
def test_duplicate_and_cross_event_seat_ids_are_rejected(booking_inventory):
    user, event, event_seat = booking_inventory
    client = APIClient()
    client.force_authenticate(user=user)

    duplicate = client.post(
        "/api/bookings/holds/",
        {
            "event_id": event.id,
            "event_seat_ids": [event_seat.id, event_seat.id],
        },
        format="json",
    )
    assert duplicate.status_code == 400

    other_event = Event.objects.create(
        name="Different Event",
        venue=event.venue,
        starts_at=event.starts_at + timedelta(days=1),
        ends_at=event.ends_at + timedelta(days=1),
    )
    wrong_event = client.post(
        "/api/bookings/holds/",
        {
            "event_id": other_event.id,
            "event_seat_ids": [event_seat.id],
        },
        format="json",
    )
    assert wrong_event.status_code == 400


@pytest.mark.django_db
def test_webhook_is_not_throttled_by_generic_api_scopes(settings):
    settings.RAZORPAY_WEBHOOK_SECRET = "test-webhook-secret"
    payload = json.dumps({"event": "payment.failed"}).encode("utf-8")
    signature = hmac.new(
        b"test-webhook-secret",
        payload,
        hashlib.sha256,
    ).hexdigest()
    client = APIClient()

    responses = [
        client.post(
            "/api/bookings/payments/webhook/",
            data=payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
            HTTP_X_RAZORPAY_EVENT_ID=f"bad-event-{index}",
        )
        for index in range(7)
    ]

    assert all(response.status_code == 400 for response in responses)
    assert all(response.status_code != 429 for response in responses)
