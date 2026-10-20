from django.urls import path

from .views import (
    BookingDetailView,
    BookingListView,
    CreateHoldView,
)

urlpatterns = [
    path("", BookingListView.as_view(), name="booking-list"),
    path(
        "holds/",
        CreateHoldView.as_view(),
        name="create-hold",
    ),
    path(
        "<int:pk>/",
        BookingDetailView.as_view(),
        name="booking-detail",
    ),
]