from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_event_listings, invalidate_seat_availability
from .models import Event, EventSeat, Seat, TicketTier, Venue


@receiver([post_save, post_delete], sender=Event)
def invalidate_event_caches(sender, instance, **kwargs):
    invalidate_event_listings()
    invalidate_seat_availability(instance.pk)


@receiver([post_save, post_delete], sender=Venue)
def invalidate_venue_event_listings(sender, instance, **kwargs):
    invalidate_event_listings()


@receiver([post_save, post_delete], sender=EventSeat)
def invalidate_event_seat_inventory(sender, instance, **kwargs):
    invalidate_seat_availability(instance.event_id)


@receiver([post_save, post_delete], sender=TicketTier)
def invalidate_ticket_tier_inventory(sender, instance, **kwargs):
    invalidate_seat_availability(instance.event_id)


def _seat_event_ids(seat_id):
    return EventSeat.objects.filter(seat_id=seat_id).values_list(
        "event_id",
        flat=True,
    )


@receiver([post_save, post_delete], sender=Seat)
def invalidate_seat_configuration(sender, instance, **kwargs):
    for event_id in _seat_event_ids(instance.pk):
        invalidate_seat_availability(event_id)
