from django.shortcuts import render

from rest_framework import generics,status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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