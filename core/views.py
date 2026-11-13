from rest_framework.response import Response
from rest_framework.decorators import api_view
from drf_spectacular.utils import extend_schema

from .serializers import HealthCheckSerializer


@extend_schema(
    responses={200: HealthCheckSerializer},
    description="Check whether the TicketFlow API is running.",
    tags=["Health"],
)
@api_view(["GET"])
def health_check(request):
    return Response({
        "status": "ok",
        "service": "Ticket API"
    })