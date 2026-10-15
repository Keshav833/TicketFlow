from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EventSeatListView,
    EventViewSet,
    VenueViewSet,
)

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")
router.register("venues", VenueViewSet, basename="venue")

urlpatterns = [
    path(
        "events/<int:event_id>/seats/",
        EventSeatListView.as_view(),
        name="event-seats",
    ),
    path("", include(router.urls)),
]