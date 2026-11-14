from rest_framework import generics,status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAdminUser
from drf_spectacular.utils import extend_schema
from config.throttling import SafeScopedRateThrottle

from .serializers import (
    BookingSerializer,
    CreateHoldSerializer,
    TicketCheckInSerializer,
    CreatePaymentOrderRequestSerializer,
    CreatePaymentOrderResponseSerializer,
    VerifyPaymentRequestSerializer,
    VerifyPaymentResponseSerializer,
    RazorpayWebhookResponseSerializer,
)
from .ticket_services import check_in_ticket


from .webhook_services import process_razorpay_webhook

from .payment_services import (
      create_razorpay_order ,
      verify_razorpay_payment,

      )
from .models import Booking
from .services import create_seat_hold


class BookingListView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    throttle_scope = "booking_read"

    def get_queryset(self):
        # Prevent schema generation from querying with AnonymousUser.
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()

        return (
            Booking.objects
            .filter(user=self.request.user)
            .prefetch_related(
                "items__event_seat__seat",
                "items__event_seat__event",
                "holds",
            )
            .order_by("-created_at")
        )


class BookingDetailView(generics.RetrieveAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    throttle_scope = "booking_read"

    def get_queryset(self):
        return (
            Booking.objects
            .filter(user=self.request.user)
            .prefetch_related(
                "items__event_seat__seat",
                "items__event_seat__event",
                "holds",
            )
        )

@extend_schema(
    request=CreateHoldSerializer,
    responses={
        201: BookingSerializer,
    },
    description="Create a temporary seat hold for an event.",
    tags=["Bookings"],
)
class CreateHoldView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "hold_create"

    def post(self, request):
        request_serializer = CreateHoldSerializer(
            data=request.data
        )
        request_serializer.is_valid(raise_exception=True)

        booking = create_seat_hold(
            user=request.user,
            **request_serializer.validated_data,
        )

        response_serializer = BookingSerializer(booking)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    request=CreatePaymentOrderRequestSerializer,
    responses={
        201: CreatePaymentOrderResponseSerializer,
    },
    description="Create or retrieve an existing pending Razorpay payment order.",
    tags=["Payments"],
)
class CreatePaymentOrderView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "payment_order"

    def post(self, request):
        request_serializer = CreatePaymentOrderRequestSerializer(
            data=request.data
        )
        request_serializer.is_valid(raise_exception=True)

        result = create_razorpay_order(
            user=request.user,
            **request_serializer.validated_data,
        )

        return Response(result, status=status.HTTP_201_CREATED)


@extend_schema(
    request=VerifyPaymentRequestSerializer,
    responses={
        200: VerifyPaymentResponseSerializer,
    },
    description="Verify Razorpay payment and confirm the booking.",
    tags=["Payments"],
)
class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "payment_verify"

    def post(self, request):
        request_serializer = VerifyPaymentRequestSerializer(
            data=request.data
        )
        request_serializer.is_valid(raise_exception=True)

        result = verify_razorpay_payment(
            user=request.user,
            **request_serializer.validated_data,
        )

        return Response(result, status=status.HTTP_200_OK)

@extend_schema(
    request={
        "application/json": {
            "type": "object",
            "description": "Raw Razorpay webhook event payload.",
        }
    },
    responses={
        200: RazorpayWebhookResponseSerializer,
    },
    description=(
        "Receive and verify Razorpay webhook events. "
        "Requires X-Razorpay-Signature and X-Razorpay-Event-Id headers."
    ),
    tags=["Payments"],
)
class RazorpayWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature")
        event_id = request.headers.get("X-Razorpay-Event-Id")

        result = process_razorpay_webhook(
            payload=request.body,
            signature=signature,
            event_id=event_id,
        )

        return Response(result, status=status.HTTP_200_OK)


@extend_schema(
    request=TicketCheckInSerializer,
    responses={
        200: {
            "type": "object",
            "properties": {
                "detail": {"type": "string"},
            },
        },
    },
    description="Verify a ticket and mark it as used.",
    tags=["Tickets"],
)
class TicketCheckInView(APIView):
    permission_classes = [IsAdminUser]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "ticket_checkin"

    def post(self, request):
        serializer = TicketCheckInSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        result = check_in_ticket(
            verification_token=serializer.validated_data[
                "verification_token"
            ]
        )

        return Response(
            result,
            status=status.HTTP_200_OK,
        )