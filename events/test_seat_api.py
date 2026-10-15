from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Event, EventSeat, Seat, TicketTier, Venue


@pytest.fixture
def inventory(db):
    venue = Venue.objects.create(
        name="LPU Auditorium",
        address="University Campus",
        city="Phagwara",
    )

    now = timezone.now()

    event = Event.objects.create(
        name="Tech Conference",
        venue=venue,
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=3),
    )

    tier = TicketTier.objects.create(
        event=event,
        name="Regular",
        price="500.00",
    )

    seat = Seat.objects.create(
        venue=venue,
        row="A",
        number=1,
    )

    event_seat = EventSeat.objects.create(
        event=event,
        seat=seat,
        ticket_tier=tier,
    )

    return venue, event, seat, event_seat


@pytest.mark.django_db
def test_list_venues(inventory):
    client = APIClient()

    response = client.get("/api/venues/")

    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_list_venue_seats(inventory):
    venue, _, _, _ = inventory
    client = APIClient()

    response = client.get(f"/api/venues/{venue.id}/seats/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["row"] == "A"


@pytest.mark.django_db
def test_list_event_seats(inventory):
    _, event, _, _ = inventory
    client = APIClient()

    response = client.get(f"/api/events/{event.id}/seats/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["ticket_tier_name"] == "Regular"
    assert str(response.data["results"][0]["price"]) == "500.00"