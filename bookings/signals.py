from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from events.cache import invalidate_seat_availability

from .models import Booking, BookingItem, Hold


@receiver(pre_save, sender=Booking)
def remember_booking_status(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and "status" not in update_fields:
        instance._previous_status = instance.status
        return
    if instance.pk:
        instance._previous_status = (
            sender.objects.filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )
    else:
        instance._previous_status = None


@receiver(post_save, sender=Booking)
def invalidate_confirmed_booking_seats(sender, instance, created, **kwargs):
    previous_status = getattr(instance, "_previous_status", None)
    if created or previous_status != instance.status:
        if created and instance.status != Booking.Status.CONFIRMED:
            return
        if not created and Booking.Status.CONFIRMED not in {
            previous_status,
            instance.status,
        }:
            return

        event_ids = instance.items.values_list(
            "event_seat__event_id",
            flat=True,
        ).distinct()
        for event_id in event_ids:
            invalidate_seat_availability(event_id)


@receiver([post_save, post_delete], sender=BookingItem)
def invalidate_booking_item_seats(sender, instance, **kwargs):
    invalidate_seat_availability(instance.event_seat.event_id)


@receiver([post_save, post_delete], sender=Hold)
def invalidate_held_seat(sender, instance, **kwargs):
    invalidate_seat_availability(instance.event_seat.event_id)
