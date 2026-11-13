
import logging

from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    # Let Django handle unexpected, unhandled exceptions as HTTP 500.
    if response is None:
        logger.error(
            "Unhandled API exception",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return None

    if isinstance(exc, ValidationError):
        message = "Validation failed."
        errors = response.data
    else:
        detail = (
            response.data.get("detail")
            if isinstance(response.data, dict)
            else None
        )
        message = str(detail) if detail else "Request failed."
        errors = None

    response.data = {
        "success": False,
        "status_code": response.status_code,
        "message": message,
        "errors": errors,
    }

    return response
