from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Event, EventSeat, Seat, Venue
from rest_framework import generics
from rest_framework.exceptions import NotFound


from .serializers import (
    EventSeatSerializer,
    EventSerializer,
    SeatSerializer,
    VenueSerializer,
)

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


# creates a read-only API endpoint to fetch venue details 
# and see a organized list of all physical seats inside a specific venue
class VenueViewSet(viewsets.ReadOnlyModelViewSet): #it automatically allows users to view a list of all venues or view a single venue's details (using your VenueSerializer). 
    queryset = Venue.objects.all().order_by("id")
    serializer_class = VenueSerializer

    @action(detail=True, methods=["get"])
    def seats(self, request, pk=None):
        venue = self.get_object()

        seats = Seat.objects.filter(
            venue=venue
        ).order_by("row", "number")

        page = self.paginate_queryset(seats)

        if page is not None:
            serializer = SeatSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = SeatSerializer(seats, many=True)
        return Response(serializer.data)


# This code creates a read-only list endpoint (like a public API URL) 
# that displays all the available seats and ticket prices for one specific event.
class EventSeatListView(generics.ListAPIView):
    serializer_class = EventSeatSerializer

    def get_queryset(self):
        event_id = self.kwargs["event_id"]

        queryset = EventSeat.objects.filter(
            event_id=event_id
        ).select_related(
            "event",
            "seat",
            "ticket_tier",
        ).order_by(
            "seat__row",
            "seat__number",
        )

        if not Event.objects.filter(pk=event_id).exists():
            raise NotFound("Event not found.")

        return queryset