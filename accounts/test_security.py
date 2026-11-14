import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_login_is_throttled_by_ip():
    user = User.objects.create_user(
        username="login_throttle_user",
        password="a-strong-password-123",
    )
    client = APIClient()

    for _ in range(5):
        assert client.post(
            "/api/auth/token/",
            {"username": user.username, "password": "a-strong-password-123"},
            format="json",
        ).status_code == 200
    throttled = client.post(
        "/api/auth/token/",
        {"username": user.username, "password": "a-strong-password-123"},
        format="json",
    )

    assert throttled.status_code == 429
    assert throttled.data["status_code"] == 429


@pytest.mark.django_db
def test_registration_is_throttled_and_rejects_weak_passwords():
    client = APIClient()
    invalid = client.post(
        "/api/auth/register/",
        {
            "username": "weak_user",
            "email": "weak@example.com",
            "password": "password",
        },
        format="json",
    )
    assert invalid.status_code == 400
    cache.clear()

    for index in range(5):
        response = client.post(
            "/api/auth/register/",
            {
                "username": f"register_user_{index}",
                "email": f"register{index}@example.com",
                "password": f"Strong!Unique-42-{index}",
            },
            format="json",
        )
        assert response.status_code == 201

    throttled = client.post(
        "/api/auth/register/",
        {
            "username": "register_user_last",
            "email": "registerlast@example.com",
            "password": "Strong!Unique-42-last",
        },
        format="json",
    )

    assert throttled.status_code == 429


@pytest.mark.django_db
def test_invalid_registration_email_is_rejected():
    response = APIClient().post(
        "/api/auth/register/",
        {
            "username": "invalid_email_user",
            "email": "not-an-email",
            "password": "Strong!Unique-42",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "email" in response.data["errors"]


@pytest.mark.django_db
def test_refresh_rotation_blacklists_the_previous_token():
    user = User.objects.create_user(
        username="refresh_rotation_user",
        password="a-strong-password-123",
    )
    old_refresh = str(RefreshToken.for_user(user))

    response = APIClient().post(
        "/api/auth/token/refresh/",
        {"refresh": old_refresh},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["refresh"] != old_refresh

    reuse = APIClient().post(
        "/api/auth/token/refresh/",
        {"refresh": old_refresh},
        format="json",
    )
    assert reuse.status_code == 401


def test_scoped_throttle_uses_the_configured_django_cache():
    assert ScopedRateThrottle.cache is cache
