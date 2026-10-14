from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from .models import Event
from .serializers import EventSerializer

# ReadOnlyModelViewSet automatically provides the list and retrieve actions.
#  It does not provide create, update, or delete actions.
class EventViewSet(viewsets.ReadOnlyModelViewSet):
    # select_related("venue") fetches the related venue in the same SQL query using a join
    # Since our serializer reads venue.name, this helps avoid an extra database query for every event.
    queryset = Event.objects.select_related("venue").all()
    serializer_class = EventSerializer

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    # filterset_fields enables filtering by venue ID
    filterset_fields = ["venue"]

    # enables text search across event names, descriptions, and venue names.
    search_fields = [
        "name",
        "description",
        "venue__name",
    ]

    # explicitly limits which fields clients can use to sort results.
    ordering_fields = [
        "name",
        "starts_at",
        "created_at",
    ]

    ordering = ["starts_at"]