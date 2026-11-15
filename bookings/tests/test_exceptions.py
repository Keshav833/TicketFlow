
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    PermissionDenied,
    ValidationError,
)

from config.exceptions import custom_exception_handler


def test_validation_error_response():
    exc = ValidationError({
        "email": ["Enter a valid email address."]
    })

    response = custom_exception_handler(exc, {})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "success": False,
        "status_code": 400,
        "message": "Validation failed.",
        "errors": {
            "email": ["Enter a valid email address."]
        },
    }


def test_authentication_error_response():
    exc = AuthenticationFailed("Authentication credentials were not provided.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data["success"] is False
    assert response.data["status_code"] == 401
    assert response.data["message"] == (
        "Authentication credentials were not provided."
    )
    assert response.data["errors"] is None


def test_permission_error_response():
    exc = PermissionDenied("You do not have permission to perform this action.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["success"] is False
    assert response.data["status_code"] == 403
    assert response.data["message"] == (
        "You do not have permission to perform this action."
    )
    assert response.data["errors"] is None


def test_conflict_error_response():
    class BookingConflict(APIException):
        status_code = status.HTTP_409_CONFLICT
        default_detail = "Ticket has already been used."

    response = custom_exception_handler(BookingConflict(), {})

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {
        "success": False,
        "status_code": 409,
        "message": "Ticket has already been used.",
        "errors": None,
    }


def test_unhandled_exception_is_logged_without_exposing_its_message(caplog):
    exc = RuntimeError("sensitive provider detail")

    response = custom_exception_handler(exc, {})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.data == {
        "success": False,
        "status_code": 500,
        "message": "An unexpected error occurred.",
        "errors": None,
    }
    assert "RuntimeError" in caplog.text
    assert "sensitive provider detail" not in caplog.text
