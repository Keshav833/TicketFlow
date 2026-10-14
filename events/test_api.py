import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from .models import Event, Venue


@pytest.fixture
def event_data(db):
    venue = Venue.objects.create(
        name="LPU Auditorium",
        address="University Campus",
        city="Phagwara",
    )

    now = timezone.now()

    Event.objects.create(
        name="Django Conference",
        venue=venue,
        description="Backend development",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=3),
    )

    Event.objects.create(
        name="Music Concert",
        venue=venue,
        description="Live music",
        starts_at=now + timedelta(days=3),
        ends_at=now + timedelta(days=3, hours=2),
    )

    return venue


@pytest.mark.django_db
def test_list_events(event_data):
    client = APIClient()

    response = client.get("/api/events/")

    assert response.status_code == 200
    assert response.data["count"] == 2


@pytest.mark.django_db
def test_search_events(event_data):
    client = APIClient()

    response = client.get(
        "/api/events/?search=Django"
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert (
        response.data["results"][0]["name"]
        == "Django Conference"
    )


@pytest.mark.django_db
def test_filter_events_by_venue(event_data):
    client = APIClient()

    response = client.get(
        f"/api/events/?venue={event_data.id}"
    )

    assert response.status_code == 200
    assert response.data["count"] == 2