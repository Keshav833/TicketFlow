
from django.core.management.base import BaseCommand

from bookings.services import expire_stale_holds


class Command(BaseCommand):
    help = "Expire overdue booking holds."

    def handle(self, *args, **options):
        count = expire_stale_holds()

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {count} hold(s)."
            )
        )
