from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from events.models import Event, EventSeat, Seat, TicketTier, Venue
from .models import Booking, BookingItem

User = get_user_model()


# booking_setup(db):  sets up a realistic initial state in a temporary test database before any test runs. 
# It generates all necessary prerequisite database records (an event venue, the event itself,
#  a seating plan, a pricing tier, two separate users, and a confirmed booking item for user_a).
@pytest.fixture
def booking_setup(db):
    user_a = User.objects.create_user(
        username="user_a",
        password="testpassword123",
    )
    user_b = User.objects.create_user(
        username="user_b",
        password="testpassword123",
    )

    venue = Venue.objects.create(
        name="Test Auditorium",
        address="Test Address",
        city="Phagwara",
    )

    now = timezone.now()

    event = Event.objects.create(
        name="Test Conference",
        venue=venue,
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=2),
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

    booking = Booking.objects.create(
        user=user_a,
        total_amount="500.00",
    )

    BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price="500.00",
    )

    return user_a, user_b, booking


# • It authenticates the client session as user_a, 
# makes an HTTP GET request to the /api/bookings/ collection endpoint,
# and asserts that user_a receives a 200 OK response containing exactly their own bookings.
@pytest.mark.django_db
def test_user_can_list_own_bookings(booking_setup):
    user_a, _, _ = booking_setup
    client = APIClient()
    client.force_authenticate(user=user_a)

    response = client.get("/api/bookings/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert len(response.data["results"][0]["items"]) == 1


# •  It logs in as user_b and attempts to directly request a specific,
# individual booking object (/api/bookings/{id}/) that belongs to user_a.
# It asserts that the system responds with a 404 Not Found error.
@pytest.mark.django_db
def test_user_cannot_retrieve_another_users_booking(booking_setup):
    _, user_b, booking = booking_setup
    client = APIClient()
    client.force_authenticate(user=user_b)

    response = client.get(f"/api/bookings/{booking.id}/")

    assert response.status_code == 404


# It initializes a completely unauthenticated,
# anonymous API client and attempts to make a GET request to the bookings list endpoint.
# It asserts that the API rejects the request with a 401 Unauthorized status.
@pytest.mark.django_db
def test_booking_list_requires_authentication(booking_setup):
    client = APIClient()

    response = client.get("/api/bookings/")

    assert response.status_code == 401