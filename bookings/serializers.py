from rest_framework import serializers

from .models import (
    Booking,
    BookingCancellation,
    BookingItem,
    PaymentReconciliationAttempt,
    Refund,
    Ticket,
)

from events.models import EventSeat

from typing import Optional

# Converts each purchased seat into readable JSON
class BookingItemSerializer(serializers.ModelSerializer):
    event_id = serializers.IntegerField(
        source="event_seat.event_id",
        read_only=True,
    )
    seat_row = serializers.CharField(
        source="event_seat.seat.row",
        read_only=True,
    )
    seat_number = serializers.IntegerField(
        source="event_seat.seat.number",
        read_only=True,
    )
    event_name = serializers.CharField(
        source="event_seat.event.name",
        read_only=True,
    )

    class Meta:
        model = BookingItem
        fields = [
            "id",
            "event_seat",
            "event_id",
            "event_name",
            "seat_row",
            "seat_number",
            "price",
        ]

class BookingCancellationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingCancellation
        fields = [
            "initiator_type",
            "reason",
            "refund_eligible",
            "refund_amount",
            "created_at",
        ]
        read_only_fields = fields


class CancelBookingRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
    )


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = [
            "id",
            "amount",
            "currency",
            "status",
            "provider_status",
            "requested_at",
            "submitted_at",
            "processed_at",
            "failed_at",
        ]
        read_only_fields = fields


class PaymentReconciliationAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentReconciliationAttempt
        fields = ["id", "payment", "source", "outcome", "detail", "created_at"]
        read_only_fields = fields


# Returns booking details with nested items
class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    hold_expires_at = serializers.SerializerMethodField()
    cancellation = BookingCancellationSerializer(read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)
# read_only=True -  Prevents clients from changing fields through this serializer
# many=True	   -    Serializes multiple items belonging to a booking

    def get_hold_expires_at(self, booking) -> Optional[str]:
        prefetched_holds = getattr(
            booking,
            "_prefetched_objects_cache",
            {},
        ).get("holds")
        holds = (
            prefetched_holds
            if prefetched_holds is not None
            else booking.holds.all()
        )
        expirations = [
            hold.expires_at
            for hold in holds
            if hold.status == "active"
        ]
        return min(expirations).isoformat() if expirations else None

    class Meta:
        model = Booking
        fields = [
            "id",
            "status",
            "total_amount",
            "created_at",
            "updated_at",
            "items",
            "hold_expires_at",
            "cancellation",
            "refunds",
        ]
        read_only_fields = fields

from rest_framework import serializers

from events.models import EventSeat


class CreateHoldSerializer(serializers.Serializer):
    event_id = serializers.IntegerField(min_value=1)

    event_seat_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=10,
    )

    def validate_event_seat_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Duplicate seat IDs are not allowed."
            )

        return value

    def validate(self, attrs):
        event_id = attrs["event_id"]
        seat_ids = attrs["event_seat_ids"]

        seats = EventSeat.objects.filter(
            event_id=event_id,
            id__in=seat_ids,
        )

        if seats.count() != len(seat_ids):
            raise serializers.ValidationError({
                "event_seat_ids": (
                    "One or more seats do not belong to this event."
                )
            })

        return attrs



class TicketCheckInSerializer(serializers.Serializer):
    verification_token = serializers.UUIDField()


class CustomerTicketSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(
        source="booking_item.booking_id",
        read_only=True,
    )
    booking_status = serializers.CharField(
        source="booking_item.booking.status",
        read_only=True,
    )
    price = serializers.DecimalField(
        source="booking_item.price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    event_id = serializers.IntegerField(
        source="booking_item.event_seat.event_id",
        read_only=True,
    )
    event_name = serializers.CharField(
        source="booking_item.event_seat.event.name",
        read_only=True,
    )
    event_starts_at = serializers.DateTimeField(
        source="booking_item.event_seat.event.starts_at",
        read_only=True,
    )
    event_ends_at = serializers.DateTimeField(
        source="booking_item.event_seat.event.ends_at",
        read_only=True,
    )
    venue_name = serializers.CharField(
        source="booking_item.event_seat.event.venue.name",
        read_only=True,
    )
    venue_city = serializers.CharField(
        source="booking_item.event_seat.event.venue.city",
        read_only=True,
    )
    seat_row = serializers.CharField(
        source="booking_item.event_seat.seat.row",
        read_only=True,
    )
    seat_number = serializers.IntegerField(
        source="booking_item.event_seat.seat.number",
        read_only=True,
    )
    tier_name = serializers.CharField(
        source="booking_item.event_seat.ticket_tier.name",
        read_only=True,
    )
    qr_available = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_number",
            "status",
            "issued_at",
            "used_at",
            "booking_id",
            "booking_status",
            "price",
            "event_id",
            "event_name",
            "event_starts_at",
            "event_ends_at",
            "venue_name",
            "venue_city",
            "seat_row",
            "seat_number",
            "tier_name",
            "qr_available",
        ]
        read_only_fields = fields

    def get_qr_available(self, ticket) -> bool:
        return bool(ticket.qr_code)



class CreatePaymentOrderRequestSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField(min_value=1)


class CreatePaymentOrderResponseSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    payment_id = serializers.IntegerField()
    razorpay_order_id = serializers.CharField()
    razorpay_key_id = serializers.CharField()
    amount = serializers.IntegerField(
        help_text="Payment amount in paise."
    )
    currency = serializers.CharField()


class VerifyPaymentRequestSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField(min_value=1)
    razorpay_order_id = serializers.CharField(max_length=100, trim_whitespace=True)
    razorpay_payment_id = serializers.CharField(max_length=255, trim_whitespace=True)
    razorpay_signature = serializers.CharField(
        max_length=128,
        min_length=64,
        trim_whitespace=True,
        write_only=True,
    )


class VerifyPaymentResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    booking_id = serializers.IntegerField()
    payment_id = serializers.IntegerField()
    payment_status = serializers.CharField()
    booking_status = serializers.CharField()


class RazorpayWebhookResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    event = serializers.CharField(required=False)
