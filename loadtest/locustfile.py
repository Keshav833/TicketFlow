import os
import random
from urllib.parse import urlparse

from locust import HttpUser, between, events, task


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ALLOW_NONLOCAL = os.getenv("LOCUST_ALLOW_NONLOCAL", "").lower() in {
    "1",
    "true",
    "yes",
}
THROTTLE_ENABLED = os.getenv("THROTTLE_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


@events.test_start.add_listener
def require_explicit_nonlocal_target(environment, **kwargs):
    target = environment.host or os.getenv(
        "LOCUST_HOST",
        "http://127.0.0.1:8000",
    )
    hostname = urlparse(target).hostname
    if hostname not in LOCAL_HOSTS and not ALLOW_NONLOCAL:
        raise RuntimeError(
            "Load tests default to localhost. Set "
            "LOCUST_ALLOW_NONLOCAL=true only for a test environment "
            "you own and have permission to load test."
        )


class EventBrowsingUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        configured_event_id = os.getenv("LOCUST_EVENT_ID")
        self.event_ids = (
            [int(configured_event_id)]
            if configured_event_id
            else []
        )
        if not self.event_ids:
            self._discover_events()

    def _discover_events(self):
        with self.client.get(
            "/api/events/",
            name="GET /api/events/ [discovery]",
            catch_response=True,
        ) as response:
            if self._is_expected_rate_limit(response, "/api/events/"):
                return
            if response.status_code != 200:
                response.failure(f"Event discovery returned {response.status_code}")
                return

            try:
                data = response.json()
                results = data.get("results", data)
                discovered_ids = [
                    int(event["id"])
                    for event in results
                    if "id" in event
                ]
            except (AttributeError, TypeError, ValueError, KeyError) as exc:
                response.failure(f"Invalid event list response: {exc}")
                return

            if not self.event_ids:
                self.event_ids = discovered_ids
            response.success()

    def _is_expected_rate_limit(self, response, request_name):
        if THROTTLE_ENABLED and response.status_code == 429:
            response.request_meta["name"] = f"429 rate-limited {request_name}"
            response.success()
            return True
        return False

    @task(5)
    def list_events(self):
        with self.client.get(
            "/api/events/",
            name="GET /api/events/",
            catch_response=True,
        ) as response:
            if self._is_expected_rate_limit(response, "/api/events/"):
                return
            if response.status_code != 200:
                response.failure(f"Event list returned {response.status_code}")

    @task(2)
    def retrieve_event(self):
        if not self.event_ids:
            return

        event_id = random.choice(self.event_ids)
        with self.client.get(
            f"/api/events/{event_id}/",
            name="GET /api/events/[id]/",
            catch_response=True,
        ) as response:
            if self._is_expected_rate_limit(response, "/api/events/[id]/"):
                return
            if response.status_code != 200:
                response.failure(f"Event detail returned {response.status_code}")

    @task(3)
    def list_event_seats(self):
        if not self.event_ids:
            return

        event_id = random.choice(self.event_ids)
        with self.client.get(
            f"/api/events/{event_id}/seats/",
            name="GET /api/events/[id]/seats/",
            catch_response=True,
        ) as response:
            if self._is_expected_rate_limit(
                response,
                "/api/events/[id]/seats/",
            ):
                return
            if response.status_code != 200:
                response.failure(f"Event seats returned {response.status_code}")
