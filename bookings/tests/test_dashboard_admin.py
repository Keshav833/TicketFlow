from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, BookingItem, OutboxEvent, Payment, Ticket
from events.models import Event, EventSeat, Seat, TicketTier, Venue


User = get_user_model()


@pytest.fixture
def dashboard_event(db):
    venue = Venue.objects.create(
        name="Dashboard Venue",
        address="Dashboard Address",
        city="Dashboard City",
    )
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        name="Dashboard Event",
        venue=venue,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
    )
    tier = TicketTier.objects.create(
        event=event,
        name="Standard",
        price=Decimal("500.00"),
    )
    seat = Seat.objects.create(venue=venue, row="A", number=1)
    event_seat = EventSeat.objects.create(
        event=event,
        seat=seat,
        ticket_tier=tier,
    )
    return event, event_seat


@pytest.mark.django_db
def test_dashboard_requires_staff_access():
    client = APIClient()

    assert client.get("/api/admin/dashboard/stats/").status_code == 401

    user = User.objects.create_user(username="dashboard_customer")
    client.force_authenticate(user=user)
    assert client.get("/api/admin/dashboard/stats/").status_code == 403


@pytest.mark.django_db
def test_dashboard_reports_counts_and_confirmed_successful_revenue(dashboard_event):
    event, event_seat = dashboard_event
    staff_user = User.objects.create_user(
        username="dashboard_staff",
        is_staff=True,
    )
    confirmed = Booking.objects.create(
        user=staff_user,
        status=Booking.Status.CONFIRMED,
        total_amount=Decimal("500.00"),
    )
    held = Booking.objects.create(
        user=staff_user,
        status=Booking.Status.HELD,
        total_amount=Decimal("500.00"),
    )
    Booking.objects.create(
        user=staff_user,
        status=Booking.Status.EXPIRED,
        total_amount=Decimal("500.00"),
    )
    Booking.objects.create(
        user=staff_user,
        status=Booking.Status.CANCELLED,
        total_amount=Decimal("500.00"),
    )
    Booking.objects.create(
        user=staff_user,
        status=Booking.Status.REFUNDED,
        total_amount=Decimal("500.00"),
    )
    payments = (
        (confirmed, Payment.Status.SUCCEEDED, "500.00"),
        (held, Payment.Status.SUCCEEDED, "1000.00"),
        (confirmed, Payment.Status.PENDING, "25.00"),
        (confirmed, Payment.Status.FAILED, "50.00"),
        (confirmed, Payment.Status.REFUNDED, "75.00"),
    )
    for index, (booking, payment_status, amount) in enumerate(payments):
        Payment.objects.create(
            booking=booking,
            idempotency_key=f"dashboard-payment-{index}",
            status=payment_status,
            amount=Decimal(amount),
        )

    for index, ticket_status in enumerate(Ticket.Status.values):
        item = BookingItem.objects.create(
            booking=confirmed,
            event_seat=event_seat,
            price=Decimal("500.00"),
        )
        Ticket.objects.create(
            booking_item=item,
            ticket_number=f"TF-DASH-{index}",
            status=ticket_status,
        )

    past_start = timezone.now() - timedelta(days=5)
    Event.objects.create(
        name="Past Dashboard Event",
        venue=event.venue,
        starts_at=past_start,
        ends_at=past_start + timedelta(hours=2),
    )

    client = APIClient()
    client.force_authenticate(user=staff_user)
    response = client.get("/api/admin/dashboard/stats/")

    assert response.status_code == 200
    assert response.data["bookings"] == {
        "total": 5,
        "confirmed": 1,
        "pending": 1,
        "expired": 1,
        "cancelled": 1,
        "refunded": 1,
    }
    assert response.data["payments"] == {
        "successful": 2,
        "pending": 1,
        "failed": 1,
        "refunded": 1,
    }
    assert response.data["revenue"] == {
        "total": "500.00",
        "today": "500.00",
        "this_month": "500.00",
    }
    assert response.data["tickets"] == {
        "issued": 1,
        "used": 1,
        "cancelled": 1,
    }
    assert response.data["events"] == {"total": 2, "upcoming": 1}


@pytest.mark.django_db
def test_dashboard_returns_zero_values_when_no_records_exist():
    staff_user = User.objects.create_user(
        username="empty_dashboard_staff",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get("/api/admin/dashboard/stats/")

    assert response.status_code == 200
    assert response.data["bookings"]["total"] == 0
    assert response.data["payments"]["successful"] == 0
    assert response.data["revenue"] == {
        "total": "0.00",
        "today": "0.00",
        "this_month": "0.00",
    }
    assert response.data["tickets"] == {
        "issued": 0,
        "used": 0,
        "cancelled": 0,
    }
    assert response.data["events"] == {"total": 0, "upcoming": 0}


@pytest.mark.django_db
def test_booking_admin_is_read_only_and_ticket_token_is_not_displayed(dashboard_event):
    _, event_seat = dashboard_event
    customer = User.objects.create_user(username="dashboard_admin_customer")
    booking = Booking.objects.create(
        user=customer,
        status=Booking.Status.CONFIRMED,
        total_amount=Decimal("500.00"),
    )
    item = BookingItem.objects.create(
        booking=booking,
        event_seat=event_seat,
        price=Decimal("500.00"),
    )
    ticket = Ticket.objects.create(
        booking_item=item,
        ticket_number="TF-ADMIN-1",
    )

    staff_user = User.objects.create_user(
        username="booking_admin_staff",
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(staff_user)

    changelist = client.get(reverse("admin:bookings_booking_changelist"))
    detail = client.get(
        reverse("admin:bookings_booking_change", args=[booking.pk])
    )
    ticket_detail = client.get(
        reverse("admin:bookings_ticket_change", args=[ticket.pk])
    )

    assert changelist.status_code == 200
    assert detail.status_code == 200
    assert ticket_detail.status_code == 200
    assert str(ticket.verification_token) not in ticket_detail.content.decode()

    booking_admin = admin.site._registry[Booking]
    ticket_admin = admin.site._registry[Ticket]
    assert not booking_admin.has_add_permission(client)
    assert {"status", "total_amount", "user"} <= set(booking_admin.readonly_fields)
    assert "qr_code" not in ticket_admin.readonly_fields


@pytest.mark.django_db
def test_outbox_event_is_searchable_and_read_only_in_admin():
    event = OutboxEvent.objects.create(
        event_type="booking_fulfillment",
        aggregate_id=42,
        idempotency_key="booking_fulfillment:42",
        payload={"booking_id": 42},
        last_error="internal error details",
    )
    staff_user = User.objects.create_user(
        username="outbox_admin_staff",
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(staff_user)

    response = client.get(reverse("admin:bookings_outboxevent_changelist"))
    detail = client.get(
        reverse("admin:bookings_outboxevent_change", args=[event.pk])
    )

    assert response.status_code == 200
    assert detail.status_code == 200
    assert event.idempotency_key in response.content.decode()
    assert "internal error details" not in detail.content.decode()

    outbox_admin = admin.site._registry[OutboxEvent]
    assert not outbox_admin.has_add_permission(client)
    assert {"status", "attempts"} <= set(outbox_admin.readonly_fields)
