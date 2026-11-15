from django.core.cache import cache
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Clear Django's default cache, including DRF throttle counters. "
        "This also clears cached event API responses."
    )

    def handle(self, *args, **options):
        cache.clear()
        self.stdout.write(
            self.style.SUCCESS(
                "Django default cache cleared (throttle counters and API cache)."
            )
        )
