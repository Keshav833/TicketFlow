import uuid

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_throttle_toggle_off_allows_200_event_requests(settings):
    settings.THROTTLE_ENABLED = False
    cache.clear()
    client = APIClient()

    statuses = [
        client.get("/api/events/").status_code
        for _ in range(200)
    ]

    assert statuses.count(200) == 200
    assert 429 not in statuses


@pytest.mark.django_db
def test_throttle_toggle_off_bypasses_explicit_view_throttle(settings):
    settings.THROTTLE_ENABLED = False
    cache.clear()
    staff_user = get_user_model().objects.create_user(
        username="throttle_toggle_staff",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=staff_user)
    url = reverse("ticket-check-in")

    statuses = [
        client.post(
            url,
            {"verification_token": str(uuid.uuid4())},
            format="json",
        ).status_code
        for _ in range(15)
    ]

    assert 429 not in statuses
    assert set(statuses) == {404}


@pytest.mark.django_db
def test_clear_throttle_cache_command_clears_default_cache():
    cache.set("test-throttle-cache-key", "counted")

    call_command("clear_throttle_cache")

    assert cache.get("test-throttle-cache-key") is None
