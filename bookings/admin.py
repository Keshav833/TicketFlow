from django.contrib import admin

# Register your models here.
from .models import Booking , BookingItem , Hold , Payment

admin.site.register(Booking)
admin.site.register(BookingItem)
admin.site.register(Hold)
admin.site.register(Payment)