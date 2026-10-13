from django.db import models
from django.db.models import Q
# Create your models here.

class Venue(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)

    def __str(self):
        return self.name

class Seat(models.Model):
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="seats",
    )

    row = models.CharField(max_length=10)
    number = models.PositiveIntegerField()

    class Meta:
        constraints = [
            #Ensures that no two seats can have the same row and number within the same venue 
            # (prevents duplicate seating).
            models.UniqueConstraint(
                fields=["venue", "row", "number"],
                name="unique_seat_per_venue",
            ),

            # Ensures that every seat number saved in the database is a positive integer 
            # starting from 1 or higher.
            models.CheckConstraint(
                condition= Q(number__gte = 1),
                name = "seat_number_at_least_one",
            )
        ]

    def __str__(self):
        return f"{self.row}{self.number}"

class Event(models.Model):
    name = models.CharField(max_length=200)

    venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name="events",
    )

    class Meta:
        constraints = [
            models.CheckConstraint( #This makes PostgreSQL reject events whose end time is not later than their start time.
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="event_end_after_start",
            ),
    ]

    description = models.TextField(blank=True)

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class TicketTier(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="ticket_tiers",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="ticket_price_nonnegative",
            ),
    ]

    name = models.CharField(max_length=100)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    def __str__(self):
        return f"{self.event.name} - {self.name}"



class EventSeat(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="event_seats",
    )

    seat = models.ForeignKey(
        Seat,
        on_delete=models.PROTECT,
        related_name="event_seats",
    )

    ticket_tier = models.ForeignKey(
        TicketTier,
        on_delete=models.PROTECT,
        related_name="event_seats",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "seat"],
                name="unique_seat_per_event",
            )
        ]

    def __str__(self):
        return f"{self.event.name} - {self.seat}"