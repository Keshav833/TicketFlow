from rest_framework import serializers

from .models import Event
from .models import EventSeat, Seat , Venue

# A serializer translates Django model objects into JSON and validates incoming data.
class EventSerializer(serializers.ModelSerializer):
    # venue_name is a readable label for the client.
    venue_name = serializers.CharField(
        source="venue.name",
        read_only=True,
    )

    class Meta:
        model = Event
        fields = [
            "id",
            "name",
            "venue",
            "venue_name",
            "description",
            "starts_at",
            "ends_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    # The validate() method catches invalid event dates at the API boundary. 
    # Our PostgreSQL constraint remains a second line of defence.
    def validate(self, attrs):
        starts_at = attrs.get(
            "starts_at",
            getattr(self.instance, "starts_at", None),
        )
        ends_at = attrs.get(
            "ends_at",
            getattr(self.instance, "ends_at", None),
        )

        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({
                "ends_at": "End time must be after start time."
            })

        return attrs

# VenueSerializer exposes venue details.
class VenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "address", "city"]

# SeatSerializer exposes physical seats.
class SeatSerializer(serializers.ModelSerializer):
    venue_name = serializers.CharField(
        source="venue.name",
        read_only=True,
    )

    class Meta:
        model = Seat
        fields = ["id", "venue", "venue_name", "row", "number"]


# EventSeatSerializer exposes the seats assigned to an event, along with their ticket tier and price.
class EventSeatSerializer(serializers.ModelSerializer):
    seat_row = serializers.CharField(
        source="seat.row",
        read_only=True,
    )
    seat_number = serializers.IntegerField(
        source="seat.number",
        read_only=True,
    )
    ticket_tier_name = serializers.CharField(
        source="ticket_tier.name",
        read_only=True,
    )
    price = serializers.DecimalField(
        source="ticket_tier.price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = EventSeat
        fields = [
            "id",
            "event",
            "seat",
            "seat_row",
            "seat_number",
            "ticket_tier",
            "ticket_tier_name",
            "price",
        ]