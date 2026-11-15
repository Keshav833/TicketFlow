from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.models import (
    Booking,
    BookingEmailDelivery,
    BookingItem,
    Hold,
    OutboxEvent,
    Payment,
    ProcessedWebhookEvent,
    Ticket,
)
from events.models import Event, EventSeat, Seat, TicketTier, Venue


@pytest.fixture
def model_records(db):
    user = get_user_model().objects.create_user(username="model_test_user")
    venue = Venue.objects.create(
        name="Model Test Venue",
        address="Model Test Address",
        city="Model Test City",
    )
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        name="Model Test Event",
        venue=venue,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
    )
    tier = TicketTier.objects.create(
        event=event,
        name="Standard",
        price=Decimal("100.00"),
    )
    seat = Seat.objects.create(venue=venue, row="A", number=1)
    event_seat = EventSeat.objects.create(
        event=event,
        seat=seat,
        ticket_tier=tier,
    )
    booking = Booking.objects.create(user=user, total_amount=Decimal("100.00"))
    item = BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price=Decimal("100.00"),
    )
    return user, event_seat, booking, item


@pytest.mark.django_db
def test_booking_and_related_model_defaults(model_records):
    user, event_seat, booking, item = model_records

    hold = Hold.objects.create(
        event_seat=event_seat,
        user=user,
        booking=booking,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    payment = Payment.objects.create(
        booking=booking,
        idempotency_key="model-test-payment",
        amount=Decimal("100.00"),
    )
    delivery = BookingEmailDelivery.objects.create(booking=booking)

    assert booking.status == Booking.Status.HELD
    assert item.booking == booking
    assert hold.status == Hold.Status.ACTIVE
    assert payment.status == Payment.Status.PENDING
    assert delivery.status == BookingEmailDelivery.Status.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize(
    "record_factory",
    [
        lambda records: Booking.objects.create(
            user=records[0],
            total_amount=Decimal("-1.00"),
        ),
        lambda records: BookingItem.objects.create(
            booking=records[2],
            event_seat=records[1],
            price=Decimal("-1.00"),
        ),
        lambda records: Payment.objects.create(
            booking=records[2],
            idempotency_key="negative-payment",
            amount=Decimal("-1.00"),
        ),
    ],
)
def test_amounts_cannot_be_negative(model_records, record_factory):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            record_factory(model_records)


@pytest.mark.django_db
def test_only_one_active_hold_can_exist_per_seat(model_records):
    user, event_seat, booking, _ = model_records
    Hold.objects.create(
        event_seat=event_seat,
        user=user,
        booking=booking,
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Hold.objects.create(
                event_seat=event_seat,
                user=user,
                booking=booking,
                expires_at=timezone.now() + timedelta(minutes=10),
            )


@pytest.mark.django_db
def test_database_enforces_payment_ticket_and_event_idempotency(model_records):
    _, event_seat, booking, item = model_records
    Payment.objects.create(
        booking=booking,
        idempotency_key="unique-payment-key",
        amount=Decimal("100.00"),
    )
    Ticket.objects.create(booking_item=item, ticket_number="MODEL-TICKET-1")
    ProcessedWebhookEvent.objects.create(
        event_id="model-webhook-event",
        event_type="payment.captured",
    )
    OutboxEvent.objects.create(
        event_type="booking_fulfillment",
        aggregate_id=booking.id,
        idempotency_key="unique-outbox-key",
    )

    duplicate_creations = (
        lambda: Payment.objects.create(
            booking=booking,
            idempotency_key="unique-payment-key",
            amount=Decimal("100.00"),
        ),
        lambda: Ticket.objects.create(
            booking_item=item,
            ticket_number="MODEL-TICKET-2",
        ),
        lambda: ProcessedWebhookEvent.objects.create(
            event_id="model-webhook-event",
            event_type="payment.captured",
        ),
        lambda: OutboxEvent.objects.create(
            event_type="booking_fulfillment",
            aggregate_id=booking.id,
            idempotency_key="unique-outbox-key",
        ),
    )

    for create_duplicate in duplicate_creations:
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                create_duplicate()
