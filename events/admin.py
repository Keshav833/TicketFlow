from django.contrib import admin
from .models import Event, EventSeat , Seat , TicketTier , Venue

admin.site.register(Venue)
admin.site.register(Seat)
admin.site.register(EventSeat)
admin.site.register(Event)
admin.site.register(TicketTier)
