import logging

from redis.exceptions import RedisError
from rest_framework.throttling import ScopedRateThrottle


logger = logging.getLogger("ticketflow")


class SafeScopedRateThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except (RedisError, ConnectionError, TimeoutError, OSError):
            logger.exception(
                "Rate-limit cache unavailable; allowing request to continue"
            )
            return True
