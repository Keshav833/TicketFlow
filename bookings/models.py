import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from events.models import EventSeat
from django.db.models import Q #add filter feature to django with OR ,NOT

class Booking(models.Model):

    class Status(models.TextChoices): #restricts application-level status choices to our defined values.
        HELD = "held", "Held"
        PAYMENT_PENDING = "payment_pending", "Payment Pending"
        CONFIRMED = "confirmed", "Confirmed"
        REFUND_PENDING = "refund_pending", "Refund Pending"
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


class ConfirmedSeat(models.Model):
    """The database-backed inventory allocation for a confirmed seat."""

    event_seat = models.OneToOneField(
        EventSeat,
        on_delete=models.PROTECT,
        related_name="confirmed_allocation",
    )
    booking_item = models.OneToOneField(
        BookingItem,
        on_delete=models.PROTECT,
        related_name="confirmed_allocation",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Confirmed allocation for event seat {self.event_seat_id}"

    

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
        REFUND_PENDING = "refund_pending", "Refund Pending"
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

    provider_refund_id = models.CharField(
        max_length=255,
        blank=True,
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



class ProcessedWebhookEvent(models.Model):
    event_id = models.CharField(
        max_length=255,
        unique=True,
    )

    event_type = models.CharField(
        max_length=100,
    )

    processed_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return f"{self.event_type}: {self.event_id}"


class OutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DISPATCHED = "dispatched", "Dispatched"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    event_type = models.CharField(max_length=64)
    aggregate_id = models.BigIntegerField(db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payload = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "available_at", "created_at"]),
            models.Index(fields=["event_type", "aggregate_id"]),
        ]

    def __str__(self):
        return f"{self.event_type}:{self.aggregate_id} ({self.status})"


class BookingEmailDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    booking = models.OneToOneField(
        Booking,
        on_delete=models.PROTECT,
        related_name="email_delivery",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self):
        return f"Email delivery for booking {self.booking_id}: {self.status}"


class Ticket(models.Model):

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        USED = "used", "Used"
        CANCELLED = "cancelled", "Cancelled"

    booking_item = models.OneToOneField(
        BookingItem,
        on_delete=models.PROTECT,
        related_name="ticket",
    )

    ticket_number = models.CharField(
        max_length=30,
        unique=True,
    )

    verification_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    qr_code = models.ImageField(
    upload_to="tickets/qr_codes/",
    blank=True,
    null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
    )

    issued_at = models.DateTimeField(auto_now_add=True)

    used_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"Ticket {self.ticket_number} - {self.status}"
