from rest_framework import serializers

from .models import Event

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