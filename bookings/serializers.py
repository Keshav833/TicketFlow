from rest_framework import serializers

from .models import Booking, BookingItem

from events.models import EventSeat

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

# Returns booking details with nested items
class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    hold_expires_at = serializers.SerializerMethodField()
# read_only=True -  Prevents clients from changing fields through this serializer
# many=True	   -    Serializes multiple items belonging to a booking

    def get_hold_expires_at(self, booking):
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