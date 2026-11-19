from django.contrib import admin

from .models import (
    Booking,
    BookingEmailDelivery,
    BookingItem,
    Hold,
    OutboxEvent,
    Payment,
    PaymentReconciliationAttempt,
    ProcessedWebhookEvent,
    Refund,
    Ticket,
)


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class BookingItemInline(ReadOnlyInline):
    model = BookingItem
    fields = ("event_name", "event_seat", "price", "created_at")
    readonly_fields = fields

    @admin.display(description="Event")
    def event_name(self, item):
        return item.event_seat.event.name

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "event_seat__event",
            "event_seat__seat",
        )


class PaymentInline(ReadOnlyInline):
    model = Payment
    fields = (
        "provider",
        "status",
        "amount",
        "provider_order_id",
        "provider_payment_id",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields


class RefundInline(ReadOnlyInline):
    model = Refund
    fields = ("amount", "currency", "status", "provider_refund_id", "requested_at", "processed_at")
    readonly_fields = fields


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "event_names",
        "status",
        "total_amount",
        "payment_status",
        "created_at",
    )
    list_filter = ("status", "created_at", "payments__status")
    search_fields = (
        "id",
        "user__email",
        "user__username",
        "items__event_seat__event__name",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = (BookingItemInline, PaymentInline, RefundInline)
    readonly_fields = (
        "user",
        "status",
        "total_amount",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .prefetch_related(
                "items__event_seat__event",
                "payments",
            )
        )

    @admin.display(description="Customer", ordering="user__username")
    def customer(self, booking):
        return f"{booking.user.username} ({booking.user.email})"

    @admin.display(description="Events")
    def event_names(self, booking):
        return ", ".join(
            sorted({item.event_seat.event.name for item in booking.items.all()})
        )

    @admin.display(description="Payment status")
    def payment_status(self, booking):
        statuses = sorted({
            payment.get_status_display()
            for payment in booking.payments.all()
        })
        return ", ".join(statuses) if statuses else "No payment"

    def has_add_permission(self, request):
        return False


@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "event_name", "event_seat", "price", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "booking__id",
        "booking__user__username",
        "booking__user__email",
        "event_seat__event__name",
    )
    readonly_fields = (
        "booking",
        "event_seat",
        "price",
        "created_at",
    )
    list_select_related = ("booking", "event_seat__event", "event_seat__seat")

    @admin.display(description="Event", ordering="event_seat__event__name")
    def event_name(self, item):
        return item.event_seat.event.name

    def has_add_permission(self, request):
        return False


@admin.register(Hold)
class HoldAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking",
        "event_name",
        "event_seat",
        "user",
        "status",
        "expires_at",
    )
    list_filter = ("status", "expires_at", "created_at")
    search_fields = (
        "booking__id",
        "user__username",
        "user__email",
        "event_seat__event__name",
    )
    readonly_fields = (
        "event_seat",
        "user",
        "booking",
        "status",
        "expires_at",
        "created_at",
    )
    list_select_related = ("booking", "user", "event_seat__event")
    date_hierarchy = "expires_at"

    @admin.display(description="Event", ordering="event_seat__event__name")
    def event_name(self, hold):
        return hold.event_seat.event.name

    def has_add_permission(self, request):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking",
        "provider",
        "status",
        "amount",
        "created_at",
        "updated_at",
    )
    list_filter = ("provider", "status", "created_at")
    search_fields = (
        "booking__id",
        "booking__user__username",
        "booking__user__email",
        "provider_order_id",
        "provider_payment_id",
    )
    readonly_fields = tuple(field.name for field in Payment._meta.fields)
    list_select_related = ("booking", "booking__user")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(PaymentReconciliationAttempt)
class PaymentReconciliationAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "source", "outcome", "initiated_by", "created_at")
    list_filter = ("source", "outcome", "created_at")
    search_fields = ("payment__id", "payment__provider_order_id", "payment__provider_payment_id")
    readonly_fields = tuple(field.name for field in PaymentReconciliationAttempt._meta.fields)
    list_select_related = ("payment", "initiated_by")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "payment", "amount", "currency", "status", "provider_refund_id", "requested_at")
    list_filter = ("status", "currency", "requested_at")
    search_fields = ("booking__id", "payment__provider_payment_id", "provider_refund_id", "idempotency_key")
    readonly_fields = tuple(field.name for field in Refund._meta.fields)
    list_select_related = ("booking", "payment")
    date_hierarchy = "requested_at"

    def has_add_permission(self, request):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_number", "booking_id", "event_name", "status", "issued_at", "used_at")
    list_filter = ("status", "issued_at")
    search_fields = (
        "ticket_number",
        "booking_item__booking__id",
        "booking_item__booking__user__email",
        "booking_item__event_seat__event__name",
    )
    readonly_fields = (
        "booking_item",
        "ticket_number",
        "status",
        "issued_at",
        "used_at",
    )
    list_select_related = (
        "booking_item__booking",
        "booking_item__event_seat__event",
    )
    date_hierarchy = "issued_at"

    @admin.display(description="Booking", ordering="booking_item__booking_id")
    def booking_id(self, ticket):
        return ticket.booking_item.booking_id

    @admin.display(description="Event", ordering="booking_item__event_seat__event__name")
    def event_name(self, ticket):
        return ticket.booking_item.event_seat.event.name

    def has_add_permission(self, request):
        return False


@admin.register(ProcessedWebhookEvent)
class ProcessedWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "processed_at")
    list_filter = ("event_type", "processed_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("event_id", "event_type", "processed_at")
    date_hierarchy = "processed_at"

    def has_add_permission(self, request):
        return False


@admin.register(BookingEmailDelivery)
class BookingEmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ("booking", "status", "attempts", "sent_at", "updated_at")
    list_filter = ("status", "updated_at")
    search_fields = ("booking__id", "booking__user__email")
    readonly_fields = tuple(field.name for field in BookingEmailDelivery._meta.fields)
    list_select_related = ("booking", "booking__user")
    date_hierarchy = "updated_at"

    def has_add_permission(self, request):
        return False


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_type",
        "aggregate_id",
        "status",
        "attempts",
        "available_at",
        "created_at",
    )
    list_filter = ("event_type", "status", "created_at")
    search_fields = ("event_type", "=aggregate_id", "idempotency_key")
    readonly_fields = (
        "event_type",
        "aggregate_id",
        "idempotency_key",
        "status",
        "attempts",
        "available_at",
        "locked_at",
        "dispatched_at",
        "processed_at",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False
