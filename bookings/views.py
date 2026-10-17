from django.shortcuts import render

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from .models import Booking
from .serializers import BookingSerializer


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
