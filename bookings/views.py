from django.http import HttpResponse
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
    CancelBookingRequestSerializer,
    CreateHoldSerializer,
    CustomerTicketSerializer,
    TicketCheckInSerializer,
    CreatePaymentOrderRequestSerializer,
    CreatePaymentOrderResponseSerializer,
    VerifyPaymentRequestSerializer,
    VerifyPaymentResponseSerializer,
    RazorpayWebhookResponseSerializer,
    PaymentReconciliationAttemptSerializer,
)
from .ticket_services import (
    build_ticket_download,
    check_in_ticket,
    customer_visible_tickets,
    read_stored_qr,
)
from .models import Booking, Payment, Ticket

from .webhook_services import process_razorpay_webhook

from .payment_services import (
      create_razorpay_order ,
      verify_razorpay_payment,

      )
from .services import cancel_booking, create_seat_hold
from .reconciliation_services import reconcile_payment


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
                "refunds",
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
                "refunds",
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
    request=CancelBookingRequestSerializer,
    responses={
        200: BookingSerializer,
    },
    description="Cancel an eligible held, pending, or confirmed booking according to the cancellation policy.",
    tags=["Bookings"],
)
class CancelBookingView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "booking_cancel"

    def post(self, request, pk):
        serializer = CancelBookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")
        booking = cancel_booking(user=request.user, booking_id=pk, reason=reason)
        return Response(BookingSerializer(booking).data)


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
    responses={200: PaymentReconciliationAttemptSerializer},
    description="Staff-only authoritative Razorpay reconciliation; it cannot force-confirm a booking.",
    tags=["Payments"],
)
class StaffPaymentReconcileView(APIView):
    permission_classes = [IsAdminUser]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "payment_reconcile"

    def post(self, request, pk):
        payment = Payment.objects.filter(pk=pk).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        reconcile_payment(
            payment_id=payment.id,
            source="staff",
            initiated_by=request.user,
        )
        attempt = payment.reconciliation_attempts.order_by("-id").first()
        return Response(PaymentReconciliationAttemptSerializer(attempt).data)

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


class CustomerTicketAccessMixin:
    permission_classes = [IsAuthenticated]
    throttle_scope = "ticket_read"
    serializer_class = CustomerTicketSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Ticket.objects.none()
        return customer_visible_tickets(self.request.user)


@extend_schema(
    responses={200: CustomerTicketSerializer(many=True)},
    description=(
        "List tickets belonging to the authenticated customer. "
        "Only tickets for confirmed, paid bookings are returned."
    ),
    tags=["Tickets"],
)
class CustomerTicketListView(CustomerTicketAccessMixin, generics.ListAPIView):
    pass


@extend_schema(
    responses={200: CustomerTicketSerializer},
    description="Retrieve one ticket owned by the authenticated customer.",
    tags=["Tickets"],
)
class CustomerTicketDetailView(CustomerTicketAccessMixin, generics.RetrieveAPIView):
    pass


class CustomerTicketFileView(CustomerTicketAccessMixin, generics.GenericAPIView):
    def get_ticket(self):
        return self.get_object()


@extend_schema(
    responses={200: {"type": "string", "format": "binary"}},
    description="Return the stored QR image for a ticket owned by the customer.",
    tags=["Tickets"],
)
class CustomerTicketQRView(CustomerTicketFileView):
    def get(self, request, pk):
        ticket = self.get_ticket()
        image = read_stored_qr(ticket)
        response = HttpResponse(image, content_type="image/png")
        response["Content-Disposition"] = 'inline; filename="qr.png"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


@extend_schema(
    responses={200: {"type": "string", "format": "binary"}},
    description="Download a ticket document built from the stored ticket record.",
    tags=["Tickets"],
)
class CustomerTicketDownloadView(CustomerTicketFileView):
    def get(self, request, pk):
        ticket = self.get_ticket()
        document, filename = build_ticket_download(ticket)
        response = HttpResponse(document, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
