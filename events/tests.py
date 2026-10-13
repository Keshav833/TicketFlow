from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Event, Seat, TicketTier, Venue


@pytest.fixture
def venue(db):
    return Venue.objects.create(
        name="LPU Auditorium",
        address="University Campus",
        city="Phagwara",
    )


@pytest.mark.django_db
def test_seat_number_must_be_positive(venue):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Seat.objects.create(
                venue=venue,
                row="A",
                number=0,
            )


@pytest.mark.django_db
def test_duplicate_seat_in_same_venue_is_rejected(venue):
    Seat.objects.create(
        venue=venue,
        row="A",
        number=1,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Seat.objects.create(
                venue=venue,
                row="A",
                number=1,
            )


@pytest.mark.django_db
def test_event_end_must_be_after_start(venue):
    now = timezone.now()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Event.objects.create(
                venue=venue,
                name="Invalid Event",
                starts_at=now,
                ends_at=now - timedelta(hours=1),
            )


@pytest.mark.django_db
def test_zero_price_ticket_is_allowed(venue):
    now = timezone.now()

    event = Event.objects.create(
        venue=venue,
        name="Free Conference",
        starts_at=now,
        ends_at=now + timedelta(hours=2),
    )

    tier = TicketTier.objects.create(
        event=event,
        name="Free",
        price=0,
    )

    assert tier.price == 0