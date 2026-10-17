from django.urls import path

from .views import BookingDetailView, BookingListView


urlpatterns = [
    path("", BookingListView.as_view(), name="booking-list"), 
    #List the authenticated user's bookings

    path(
        "<int:pk>/",
        BookingDetailView.as_view(),
        name="booking-detail",
    ),
    # Retrieve one of that user's bookings
]