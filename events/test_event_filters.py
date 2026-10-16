from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Event, Venue


@pytest.fixture
def event_listing(db):
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
        starts_at=now + timedelta(days=3),
        ends_at=now + timedelta(days=3, hours=2),
    )

    Event.objects.create(
        name="Music Concert",
        venue=venue,
        description="Live music",
        starts_at=now + timedelta(days=10),
        ends_at=now + timedelta(days=10, hours=2),
    )

    return venue, now


@pytest.mark.django_db
def test_filter_events_by_start_date(event_listing):
    _, now = event_listing
    client = APIClient()

    cutoff = (now + timedelta(days=5)).isoformat()

    response = client.get(
        "/api/events/",
        {"starts_after": cutoff},
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["name"] == "Music Concert"


@pytest.mark.django_db
def test_search_and_date_filter_can_be_combined(event_listing):
    _, now = event_listing
    client = APIClient()

    response = client.get(
        "/api/events/",
        {
            "search": "Music",
            "starts_before": (
                now + timedelta(days=15)
            ).isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_invalid_date_range_is_rejected(event_listing):
    _, now = event_listing
    client = APIClient()

    response = client.get(
        "/api/events/",
        {
            "starts_after": (
                now + timedelta(days=10)
            ).isoformat(),
            "starts_before": (
                now + timedelta(days=2)
            ).isoformat(),
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_no_matching_events_returns_empty_results(event_listing):
    client = APIClient()

    response = client.get(
        "/api/events/",
        {"search": "NonexistentEventXYZ"},
    )

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["results"] == []