import pytest
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from bookings.models import Booking
from bookings.services import transition_booking


@pytest.mark.django_db
def test_held_booking_can_enter_payment(db):
    user = get_user_model().objects.create_user(
        username="state_test_user",
        password="test-password",
    )

    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.HELD,
        total_amount="499.00",
    )

    transition_booking(
        booking=booking,
        new_status=Booking.Status.PAYMENT_PENDING,
    )

    booking.refresh_from_db()
    assert booking.status == Booking.Status.PAYMENT_PENDING


@pytest.mark.django_db
def test_confirmed_booking_cannot_return_to_payment(db):
    user = get_user_model().objects.create_user(
        username="state_test_user_2",
        password="test-password",
    )

    booking = Booking.objects.create(
        user=user,
        status=Booking.Status.CONFIRMED,
        total_amount="499.00",
    )

    with pytest.raises(ValidationError):
        transition_booking(
            booking=booking,
            new_status=Booking.Status.PAYMENT_PENDING,
        )

    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "current_status,new_status,should_succeed",
    [
        ("held", "expired", True),
        ("held", "cancelled", True),
        ("payment_pending", "confirmed", True),
        ("payment_pending", "expired", True),
        ("confirmed", "expired", False),
        ("refunded", "confirmed", False),
    ],
)
def test_booking_state_transitions(
    current_status,
    new_status,
    should_succeed,
):
    user = get_user_model().objects.create_user(
        username=f"user_{current_status}_{new_status}",
        password="test-password",
    )

    booking = Booking.objects.create(
        user=user,
        status=current_status,
        total_amount="499.00",
    )

    if should_succeed:
        transition_booking(
            booking=booking,
            new_status=new_status,
        )
        booking.refresh_from_db()
        assert booking.status == new_status
    else:
        with pytest.raises(ValidationError):
            transition_booking(
                booking=booking,
                new_status=new_status,
            )

        booking.refresh_from_db()
        assert booking.status == current_status



@pytest.mark.django_db
def test_unknown_current_status_raises_validation_error():
    User = get_user_model()
    user = User.objects.create_user(
        username="invalid_status_user",
        password="testpass123",
    )

    booking = Booking.objects.create(
        user=user,
        status="unknown_status",
        total_amount=100,
    )

    with pytest.raises(ValidationError):
        transition_booking(
            booking=booking,
            new_status=Booking.Status.CONFIRMED,
        )