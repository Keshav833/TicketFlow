from django.shortcuts import render

from rest_framework import generics,status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from .payment_services import (
      create_razorpay_order ,
      verify_razorpay_payment,

      )
from .models import Booking
from .serializers import BookingSerializer,CreateHoldSerializer
from .services import create_seat_hold


class BookingListView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Booking.objects
            .filter(user=self.request.user)
            # prefetch_related() calls optimize the nested item queries.
            .prefetch_related(
                "items__event_seat__seat",
                "items__event_seat__event",
            )
            .order_by("-created_at")
        )


class BookingDetailView(generics.RetrieveAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Booking.objects
            .filter(user=self.request.user)
            .prefetch_related(
                "items__event_seat__seat",
                "items__event_seat__event",
            )
        )

class CreateHoldView(APIView):
    permission_classes = [IsAuthenticated]

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


class CreatePaymentOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        booking_id = request.data.get("booking_id")

        if not booking_id:
            return Response(
                {"detail": "booking_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = create_razorpay_order(
                user=request.user,
                booking_id=booking_id,
            )
        except ValidationError as exc:
            return Response(
                {"detail": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        required_fields = [
            "booking_id",
            "razorpay_order_id",
            "razorpay_payment_id",
            "razorpay_signature",
        ]

        missing_fields = [
            field for field in required_fields
            if not request.data.get(field)
        ]

        if missing_fields:
            return Response(
                {
                    "detail": "Missing required fields.",
                    "fields": missing_fields,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = verify_razorpay_payment(
                user=request.user,
                booking_id=request.data["booking_id"],
                razorpay_order_id=request.data["razorpay_order_id"],
                razorpay_payment_id=request.data["razorpay_payment_id"],
                razorpay_signature=request.data["razorpay_signature"],
            )
        except ValidationError as exc:
            return Response(
                {"detail": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result, status=status.HTTP_200_OK)
