from django.urls import path

from .views import (
    BookingDetailView,
    BookingListView,
    CreateHoldView,
    CreatePaymentOrderView,
    VerifyPaymentView,
    RazorpayWebhookView,
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
    path(
    "payments/create-order/",
    CreatePaymentOrderView.as_view(),
    name="create-payment-order",
    ),
    path(
    "payments/webhook/",
    RazorpayWebhookView.as_view(),
    name="razorpay-webhook",
    ),
    path(
    "payments/verify/",
    VerifyPaymentView.as_view(),
    name="verify-payment",
),
]