import hashlib
import json
import logging
from urllib.parse import urlencode

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction


logger = logging.getLogger("ticketflow")
CACHE_MISS = object()

EVENT_LIST_VERSION_KEY = "ticketflow:event-list:version"
SEAT_AVAILABILITY_VERSION_PREFIX = "ticketflow:event:{event_id}:seat-availability:version"


def _request_cache_suffix(request):
    query_params = getattr(request, "query_params", request.GET)
    query = urlencode(sorted(query_params.lists()), doseq=True)
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        identity = f"user-{user.pk}-staff-{int(user.is_staff)}-super-{int(user.is_superuser)}"
    else:
        identity = "anonymous"

    return f"{identity}:{query_hash}"


def _version(key):
    try:
        value = cache.get(key)
    except Exception:
        logger.exception("Cache read failed for version key %s", key)
        return "0"

    return str(value) if value is not None else "0"


def event_listing_cache_key(request):
    version = _version(EVENT_LIST_VERSION_KEY)
    suffix = _request_cache_suffix(request)
    return (
        f"ticketflow:event-list:v{version}:{suffix}",
        EVENT_LIST_VERSION_KEY,
        version,
    )


def seat_availability_cache_key(event_id, request):
    version_key = SEAT_AVAILABILITY_VERSION_PREFIX.format(event_id=event_id)
    version = _version(version_key)
    suffix = _request_cache_suffix(request)
    return (
        f"ticketflow:event:{event_id}:seat-availability:v{version}:{suffix}",
        version_key,
        version,
    )


def get_cached_response(key):
    try:
        serialized = cache.get(key)
    except Exception:
        logger.exception("Cache read failed for response key %s", key)
        return CACHE_MISS

    if serialized is None:
        return CACHE_MISS

    try:
        return json.loads(serialized)
    except (TypeError, ValueError):
        logger.exception("Invalid cached response for key %s", key)
        return CACHE_MISS


def set_cached_response(key, version_key, expected_version, data, timeout):
    try:
        serialized = json.dumps(data, cls=DjangoJSONEncoder)
    except (TypeError, ValueError):
        logger.exception("Response could not be serialized for caching")
        return

    if _version(version_key) != expected_version:
        return

    try:
        cache.set(key, serialized, timeout=timeout)
    except Exception:
        logger.exception("Cache write failed for response key %s", key)


def _increment_version(key):
    try:
        if not cache.add(key, 1, timeout=None):
            cache.incr(key)
    except ValueError:
        try:
            cache.set(key, 1, timeout=None)
        except Exception:
            logger.exception("Cache invalidation failed for version key %s", key)
    except Exception:
        logger.exception("Cache invalidation failed for version key %s", key)


def invalidate_event_listings():
    transaction.on_commit(
        lambda: _increment_version(EVENT_LIST_VERSION_KEY),
        robust=True,
    )


def invalidate_seat_availability(event_id):
    version_key = SEAT_AVAILABILITY_VERSION_PREFIX.format(event_id=event_id)
    transaction.on_commit(
        lambda: _increment_version(version_key),
        robust=True,
    )
