
import logging

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("ticketflow")


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        logger.error(
            "Unhandled API exception (%s)",
            type(exc).__name__,
        )
        response = Response(
            {
                "success": False,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": "An unexpected error occurred.",
                "errors": None,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return response

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
