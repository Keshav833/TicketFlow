from django.urls import path

from .views import (
    CustomerTicketDetailView,
    CustomerTicketDownloadView,
    CustomerTicketListView,
    CustomerTicketQRView,
)

urlpatterns = [
    path("", CustomerTicketListView.as_view(), name="customer-ticket-list"),
    path("<int:pk>/", CustomerTicketDetailView.as_view(), name="customer-ticket-detail"),
    path("<int:pk>/qr/", CustomerTicketQRView.as_view(), name="customer-ticket-qr"),
    path(
        "<int:pk>/download/",
        CustomerTicketDownloadView.as_view(),
        name="customer-ticket-download",
    ),
]
