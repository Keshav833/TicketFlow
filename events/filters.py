import django_filters
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from .models import Event


# venue: filter by venue ID.

# starts_after: include events starting at or after a given time.

# starts_before: include events starting at or before a given time.
class EventFilter(django_filters.FilterSet):
    starts_after = django_filters.IsoDateTimeFilter(
        field_name="starts_at",
        lookup_expr="gte",
    )

    starts_before = django_filters.IsoDateTimeFilter(
        field_name="starts_at",
        lookup_expr="lte",
    )

    class Meta:
        model = Event
        fields = ["venue"]

# The filter class validates the requested range before applying it.
#  The API should return a client error for an invalid range.
    def filter_queryset(self, queryset):
        after = self.form.cleaned_data.get("starts_after")
        before = self.form.cleaned_data.get("starts_before")

        if after and before and after > before:
            raise ValidationError({
                "date_range": (
                    "starts_after must be earlier than or equal "
                    "to starts_before."
                )
            })

        return super().filter_queryset(queryset)