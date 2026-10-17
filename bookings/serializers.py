from rest_framework import serializers

from .models import Booking, BookingItem


# Converts each purchased seat into readable JSON
class BookingItemSerializer(serializers.ModelSerializer):
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
            "event_name",
            "seat_row",
            "seat_number",
            "price",
        ]

# Returns booking details with nested items
class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
# read_only=True -  Prevents clients from changing fields through this serializer
# many=True	   -    Serializes multiple items belonging to a booking

    class Meta:
        model = Booking
        fields = [
            "id",
            "status",
            "total_amount",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = fields