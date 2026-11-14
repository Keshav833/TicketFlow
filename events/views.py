from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from django.db.models import Exists, OuterRef
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from .models import Event, EventSeat, Seat, Venue
from rest_framework import generics
from rest_framework.exceptions import NotFound
from .filters import BoundedEventSearchFilter, EventFilter
from bookings.models import Booking, BookingItem, Hold
from drf_spectacular.utils import extend_schema

from .serializers import (
    EventSeatSerializer,
    EventSerializer,
    SeatSerializer,
    VenueSerializer,
)
from .cache import (
    CACHE_MISS,
    event_listing_cache_key,
    get_cached_response,
    seat_availability_cache_key,
    set_cached_response,
)

# ReadOnlyModelViewSet automatically provides the list and retrieve actions.
#  It does not provide create, update, or delete actions.
class EventViewSet(viewsets.ReadOnlyModelViewSet):
    # select_related("venue") fetches the related venue in the same SQL query using a join
    # Since our serializer reads venue.name, this helps avoid an extra database query for every event.
    queryset = Event.objects.select_related("venue").all()
    serializer_class = EventSerializer
    permission_classes = [AllowAny]
    throttle_scope = "event_browsing"

    filter_backends = [
        DjangoFilterBackend,
        BoundedEventSearchFilter,
        filters.OrderingFilter,
    ]


    # filterset_fields enables filtering by venue ID
    filterset_class = EventFilter

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

    def list(self, request, *args, **kwargs):
        key, version_key, version = event_listing_cache_key(request)
        cached_data = get_cached_response(key)
        if cached_data is not CACHE_MISS:
            return Response(cached_data)

        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            set_cached_response(
                key,
                version_key,
                version,
                response.data,
                settings.EVENT_LIST_CACHE_TTL,
            )
        return response

    def retrieve(self, request, *args, **kwargs):
        key, version_key, version = event_listing_cache_key(request)
        event_id = kwargs.get(self.lookup_field, kwargs.get("pk"))
        detail_key = f"ticketflow:event-detail:{event_id}:{key}"
        cached_data = get_cached_response(detail_key)
        if cached_data is not CACHE_MISS:
            return Response(cached_data)

        response = super().retrieve(request, *args, **kwargs)
        if response.status_code == 200:
            set_cached_response(
                detail_key,
                version_key,
                version,
                response.data,
                settings.EVENT_LIST_CACHE_TTL,
            )
        return response


# creates a read-only API endpoint to fetch venue details 
# and see a organized list of all physical seats inside a specific venue
class VenueViewSet(viewsets.ReadOnlyModelViewSet): #it automatically allows users to view a list of all venues or view a single venue's details (using your VenueSerializer). 
    queryset = Venue.objects.all().order_by("id")
    serializer_class = VenueSerializer
    permission_classes = [AllowAny]
    throttle_scope = "event_browsing"

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
@extend_schema(
    responses={200: EventSeatSerializer(many=True)},
    description="List seats and their availability for a specific event.",
    tags=["Events"],
)
class EventSeatListView(generics.ListAPIView):
    serializer_class = EventSeatSerializer
    permission_classes = [AllowAny]
    throttle_scope = "seat_availability"

    def list(self, request, *args, **kwargs):
        key, version_key, version = seat_availability_cache_key(
            self.kwargs["event_id"],
            request,
        )
        cached_data = get_cached_response(key)
        if cached_data is not CACHE_MISS:
            return Response(cached_data)

        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            set_cached_response(
                key,
                version_key,
                version,
                response.data,
                settings.SEAT_AVAILABILITY_CACHE_TTL,
            )
        return response

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EventSeat.objects.none()

        event_id = self.kwargs["event_id"]

        queryset = EventSeat.objects.filter(
            event_id=event_id
        ).select_related(
            "event",
            "seat",
            "ticket_tier",
        ).annotate(
            is_sold=Exists(
                BookingItem.objects.filter(
                    event_seat_id=OuterRef("pk"),
                    booking__status=Booking.Status.CONFIRMED,
                )
            ),
            has_active_hold=Exists(
                Hold.objects.filter(
                    event_seat_id=OuterRef("pk"),
                    status=Hold.Status.ACTIVE,
                    expires_at__gt=timezone.now(),
                )
            ),
        ).order_by(
            "seat__row",
            "seat__number",
        )

        if not Event.objects.filter(pk=event_id).exists():
            raise NotFound("Event not found.")

        return queryset