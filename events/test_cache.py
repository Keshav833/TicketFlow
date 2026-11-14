from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from bookings.models import Booking, BookingItem, Hold
from bookings.services import (
    create_seat_hold,
    expire_stale_holds,
    start_booking_payment,
)
from events.cache import (
    CACHE_MISS,
    event_listing_cache_key,
    get_cached_response,
    seat_availability_cache_key,
)
from events.models import Event, EventSeat, Seat, TicketTier, Venue
from events.views import EventSeatListView, EventViewSet
from users.models import User


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ticketflow-event-cache-tests",
        }
    }
    cache.clear()


@pytest.fixture
def inventory(db):
    venue = Venue.objects.create(
        name="Cache Test Venue",
        address="Test Address",
        city="Test City",
    )
    starts_at = timezone.now() + timedelta(days=2)
    event = Event.objects.create(
        name="Cache Conference",
        venue=venue,
        description="Caching tests",
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
    return venue, event, seat, event_seat


@pytest.mark.django_db
def test_event_listing_caches_serialized_response(inventory, monkeypatch):
    client = APIClient()
    first_response = client.get("/api/events/")
    assert first_response.status_code == 200
    assert first_response.data["results"][0]["name"] == "Cache Conference"

    def database_access_forbidden(*args, **kwargs):
        raise AssertionError("event listing should be served from cache")

    monkeypatch.setattr(EventViewSet, "get_queryset", database_access_forbidden)
    cached_response = client.get("/api/events/")
    assert cached_response.status_code == 200
    assert cached_response.data == first_response.data


@pytest.mark.django_db
def test_event_listing_cache_varies_by_filters_and_page(inventory):
    venue, event, _, _ = inventory
    starts_at = event.starts_at + timedelta(days=1)
    second_event = Event.objects.create(
        name="Another Conference",
        venue=venue,
        description="Another event",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
    )
    client = APIClient()

    all_events = client.get("/api/events/")
    filtered = client.get("/api/events/", {"search": "Another"})
    assert all_events.data["count"] == 2
    assert filtered.data["count"] == 1
    assert filtered.data["results"][0]["id"] == second_event.id

    Event.objects.create(
        name="Third Conference",
        venue=venue,
        description="Third event",
        starts_at=starts_at + timedelta(days=1),
        ends_at=starts_at + timedelta(days=1, hours=2),
    )
    for index in range(8):
        Event.objects.create(
            name=f"Paged Conference {index}",
            venue=venue,
            description="Pagination test",
            starts_at=starts_at + timedelta(days=index + 2),
            ends_at=starts_at + timedelta(days=index + 2, hours=2),
        )

    page_one = client.get("/api/events/", {"page": 1})
    page_two = client.get("/api/events/", {"page": 2})
    assert page_one.data["count"] == 11
    assert page_two.data["count"] == 11
    assert page_one.data["results"][0]["id"] != page_two.data["results"][0]["id"]


@pytest.mark.django_db
def test_search_length_is_bounded_and_page_size_is_fixed(inventory):
    venue, event, _, _ = inventory
    for index in range(10):
        Event.objects.create(
            name=f"Page Limit Event {index}",
            venue=venue,
            starts_at=event.starts_at + timedelta(days=index + 1),
            ends_at=event.ends_at + timedelta(days=index + 1),
        )
    client = APIClient()

    oversized_search = client.get(
        "/api/events/",
        {"search": "x" * 201},
    )
    assert oversized_search.status_code == 400

    oversized_page_size = client.get(
        "/api/events/",
        {"page_size": 1000},
    )
    assert oversized_page_size.status_code == 200
    assert len(oversized_page_size.data["results"]) == 10


@pytest.mark.django_db
def test_event_browsing_scope_returns_429_after_configured_limit(inventory):
    client = APIClient()
    for _ in range(100):
        assert client.get("/api/events/").status_code == 200

    throttled = client.get("/api/events/")
    assert throttled.status_code == 429
    assert throttled.data["status_code"] == 429


@pytest.mark.django_db
def test_seat_availability_scope_returns_429_after_configured_limit(inventory):
    _, event, _, _ = inventory
    client = APIClient()
    endpoint = f"/api/events/{event.id}/seats/"
    for _ in range(60):
        assert client.get(endpoint).status_code == 200

    throttled = client.get(endpoint)
    assert throttled.status_code == 429


@pytest.mark.django_db(transaction=True)
def test_event_create_update_delete_invalidate_listing_cache(inventory):
    venue, event, _, _ = inventory
    client = APIClient()
    assert client.get("/api/events/").data["count"] == 1

    event.name = "Updated Cache Conference"
    event.save()
    updated = client.get("/api/events/")
    assert updated.data["results"][0]["name"] == "Updated Cache Conference"

    another_event = Event.objects.create(
        name="New Cache Event",
        venue=venue,
        starts_at=event.starts_at + timedelta(days=1),
        ends_at=event.ends_at + timedelta(days=1),
    )
    assert client.get("/api/events/").data["count"] == 2

    another_event.delete()
    event.event_seats.all().delete()
    event.ticket_tiers.all().delete()
    event.delete()
    assert client.get("/api/events/").data["count"] == 0


@pytest.mark.django_db
def test_invalid_event_listing_response_is_not_cached(inventory):
    client = APIClient()
    params = {
        "starts_after": (timezone.now() + timedelta(days=3)).isoformat(),
        "starts_before": (timezone.now() + timedelta(days=1)).isoformat(),
    }
    response = client.get(
        "/api/events/",
        params,
    )

    assert response.status_code == 400
    request = APIRequestFactory().get("/api/events/", params)
    request.user = SimpleNamespace(
        is_authenticated=False,
        is_staff=False,
        is_superuser=False,
    )
    key, _, _ = event_listing_cache_key(request)
    assert get_cached_response(key) is CACHE_MISS


@pytest.mark.django_db
def test_event_listing_cache_keys_include_query_and_user(inventory):
    factory = APIRequestFactory()
    first_request = factory.get("/api/events/", {"search": "Cache"})
    first_request.user = SimpleNamespace(
        is_authenticated=True,
        pk=1,
        is_staff=False,
        is_superuser=False,
    )
    second_request = factory.get("/api/events/", {"search": "Other"})
    second_request.user = SimpleNamespace(
        is_authenticated=True,
        pk=1,
        is_staff=False,
        is_superuser=False,
    )
    third_request = factory.get("/api/events/", {"search": "Cache"})
    third_request.user = SimpleNamespace(
        is_authenticated=True,
        pk=2,
        is_staff=False,
        is_superuser=False,
    )

    first_key = event_listing_cache_key(first_request)[0]
    assert first_key != event_listing_cache_key(second_request)[0]
    assert first_key != event_listing_cache_key(third_request)[0]


@pytest.mark.django_db
def test_seat_availability_cache_is_per_event_and_serves_repeated_requests(
    inventory,
    monkeypatch,
):
    venue, event, _, _ = inventory
    second_event = Event.objects.create(
        name="Second Event",
        venue=venue,
        starts_at=event.starts_at + timedelta(days=1),
        ends_at=event.ends_at + timedelta(days=1),
    )
    tier = TicketTier.objects.create(
        event=second_event,
        name="Standard",
        price="500.00",
    )
    second_seat = Seat.objects.create(venue=venue, row="B", number=1)
    EventSeat.objects.create(
        event=second_event,
        seat=second_seat,
        ticket_tier=tier,
    )
    client = APIClient()

    first = client.get(f"/api/events/{event.id}/seats/")
    other_event = client.get(f"/api/events/{second_event.id}/seats/")
    assert first.data["results"][0]["availability_status"] == "available"
    assert other_event.data["results"][0]["availability_status"] == "available"

    def database_access_forbidden(*args, **kwargs):
        raise AssertionError("seat availability should be served from cache")

    monkeypatch.setattr(EventSeatListView, "get_queryset", database_access_forbidden)
    repeated = client.get(f"/api/events/{event.id}/seats/")
    assert repeated.data == first.data

    factory = APIRequestFactory()
    request = factory.get(f"/api/events/{event.id}/seats/")
    request.user = SimpleNamespace(
        is_authenticated=False,
        is_staff=False,
        is_superuser=False,
    )
    first_key = seat_availability_cache_key(event.id, request)[0]
    second_key = seat_availability_cache_key(second_event.id, request)[0]
    assert first_key != second_key


@pytest.mark.django_db(transaction=True)
def test_hold_creation_and_expiry_invalidate_availability(inventory):
    _, event, _, event_seat = inventory
    client = APIClient()
    user = User.objects.create_user(username="availability-hold-user")
    endpoint = f"/api/events/{event.id}/seats/"

    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"
    booking = create_seat_hold(
        user=user,
        event_id=event.id,
        event_seat_ids=[event_seat.id],
    )
    assert client.get(endpoint).data["results"][0]["availability_status"] == "held"

    Hold.objects.filter(booking=booking).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert expire_stale_holds() == 1
    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"


@pytest.mark.django_db(transaction=True)
def test_expired_hold_discovered_during_payment_invalidates_availability(inventory):
    _, event, _, event_seat = inventory
    client = APIClient()
    user = User.objects.create_user(username="availability-payment-user")
    endpoint = f"/api/events/{event.id}/seats/"
    booking = create_seat_hold(
        user=user,
        event_id=event.id,
        event_seat_ids=[event_seat.id],
    )
    assert client.get(endpoint).data["results"][0]["availability_status"] == "held"

    Hold.objects.filter(booking=booking).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(ValidationError, match="hold expired"):
        start_booking_payment(user=user, booking_id=booking.id)

    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"


@pytest.mark.django_db(transaction=True)
def test_cancelled_hold_and_ticket_tier_change_invalidate_availability(inventory):
    _, event, _, event_seat = inventory
    client = APIClient()
    user = User.objects.create_user(username="availability-cancel-user")
    endpoint = f"/api/events/{event.id}/seats/"

    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"
    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.HELD,
        total_amount="500.00",
    )
    BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price="500.00",
    )
    hold = Hold.objects.create(
        event_seat=event_seat,
        user=user,
        booking=booking,
        status=Hold.Status.ACTIVE,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    assert client.get(endpoint).data["results"][0]["availability_status"] == "held"

    hold.status = Hold.Status.CANCELLED
    hold.save(update_fields=["status"])
    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"

    tier = event_seat.ticket_tier
    tier.price = "750.00"
    tier.save(update_fields=["price"])
    refreshed = client.get(endpoint)
    assert refreshed.data["results"][0]["price"] == "750.00"


@pytest.mark.django_db(transaction=True)
def test_booking_confirmation_invalidates_availability(inventory):
    _, event, _, event_seat = inventory
    client = APIClient()
    user = User.objects.create_user(username="availability-sale-user")
    endpoint = f"/api/events/{event.id}/seats/"

    assert client.get(endpoint).data["results"][0]["availability_status"] == "available"
    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.HELD,
        total_amount="500.00",
    )
    BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price="500.00",
    )
    booking.status = Booking.Status.CONFIRMED
    booking.save(update_fields=["status"])

    assert client.get(endpoint).data["results"][0]["availability_status"] == "sold"


@pytest.mark.django_db(transaction=True)
def test_stale_availability_cache_never_authorizes_double_hold(inventory):
    _, event, _, event_seat = inventory
    client = APIClient()
    first_user = User.objects.create_user(username="first-hold-user")
    second_user = User.objects.create_user(username="second-hold-user")

    assert client.get(f"/api/events/{event.id}/seats/").data["results"][0][
        "availability_status"
    ] == "available"
    create_seat_hold(
        user=first_user,
        event_id=event.id,
        event_seat_ids=[event_seat.id],
    )

    with pytest.raises(ValidationError, match="currently held"):
        create_seat_hold(
            user=second_user,
            event_id=event.id,
            event_seat_ids=[event_seat.id],
        )


@pytest.mark.django_db
def test_cache_read_and_write_failures_fall_back_to_database(inventory, monkeypatch):
    def cache_failure(*args, **kwargs):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr("events.cache.cache.get", cache_failure)
    monkeypatch.setattr("events.cache.cache.set", cache_failure)
    response = APIClient().get("/api/events/")

    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db(transaction=True)
def test_cache_invalidation_failure_is_logged(monkeypatch, caplog):
    from events.cache import invalidate_event_listings

    def cache_failure(*args, **kwargs):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr("events.cache.cache.add", cache_failure)
    with caplog.at_level("ERROR", logger="ticketflow"):
        invalidate_event_listings()

    assert "Cache invalidation failed" in caplog.text
