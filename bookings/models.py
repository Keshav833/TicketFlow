from django.conf import settings
from django.db import models
from events.models import EventSeat
from django.db.models import Q #add filter feature to django with OR ,NOT

class Booking(models.Model):

    class Status(models.TextChoices): #restricts application-level status choices to our defined values.
        HELD = "held", "Held"
        PAYMENT_PENDING = "payment_pending", "Payment Pending"
        CONFIRMED = "confirmed", "Confirmed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,#references our custom user model without hardcoding its class.
        on_delete=models.PROTECT,#prevents deleting a user who has booking records.
        related_name="bookings",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="booking_total_nonnegative",
            ),
    ]

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.HELD,
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking #{self.pk} - {self.status}"
    


class BookingItem(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="items",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="booking_item_price_nonnegative",
            ),
    ]

    event_seat = models.ForeignKey(
        EventSeat,
        on_delete=models.PROTECT,
        related_name="booking_items",
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.booking_id} - {self.event_seat_id}"

    

class Hold(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CONVERTED = "converted", "Converted"
        CANCELLED = "cancelled", "Cancelled"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_seat"],
                condition=models.Q(status="active"),
                name="unique_active_hold_per_event_seat",
            ),
    ]

    event_seat = models.ForeignKey(
        EventSeat,
        on_delete=models.PROTECT,
        related_name="holds",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="holds",
    )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="holds",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    # We use expires_at rather than storing "10 minutes" as a duration.
    # When creating a hold, we'll calculate its expiry time.

    def __str__(self):
        return f"Hold #{self.pk} - {self.status}"

class Payment(models.Model):

    
    class Status(models.TextChoices):
        CREATING = "creating", "Creating"
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"


    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payment_amount_nonnegative",
            ),
    ]

    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    provider = models.CharField(
        max_length=30,
        default="razorpay",
    )

    provider_payment_id = models.CharField(
        max_length=255,
        blank=True,
    )

    provider_order_id = models.CharField(
    max_length=100,
    blank=True,
    db_index=True,
    )

    #The unique idempotency_key gives us a database-level guarantee that the same key cannot be recorded twice.
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment #{self.pk} - {self.status}"