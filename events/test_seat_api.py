from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, BookingItem, Hold
from django.contrib.auth import get_user_model
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
    assert response.data["results"][0]["availability_status"] == "available"


@pytest.mark.django_db
def test_event_seat_availability_tracks_active_holds_and_sales(inventory):
    _, event, _, event_seat = inventory
    user = get_user_model().objects.create_user(username="seat-status-user")
    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.HELD,
        total_amount="500.00",
    )
    Hold.objects.create(
        event_seat=event_seat,
        user=user,
        booking=booking,
        status=Hold.Status.ACTIVE,
        expires_at=timezone.now() + timedelta(minutes=5),
    )

    client = APIClient()
    held_response = client.get(f"/api/events/{event.id}/seats/")

    assert held_response.data["results"][0]["availability_status"] == "held"

    booking.status = Booking.Status.CONFIRMED
    booking.save(update_fields=["status"])
    BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price="500.00",
    )
    sold_response = client.get(f"/api/events/{event.id}/seats/")

    assert sold_response.data["results"][0]["availability_status"] == "sold"