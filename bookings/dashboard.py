from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking, Payment, Ticket
from config.throttling import SafeScopedRateThrottle
from events.models import Event


def _local_day_bounds(day):
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
    return start, end


class AdminDashboardStatsView(APIView):
    permission_classes = [IsAdminUser]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "admin_dashboard"

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate(now)
        today_start, tomorrow_start = _local_day_bounds(today)
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(
                year=month_start.year + 1,
                month=1,
            )
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)
        month_start_at, _ = _local_day_bounds(month_start)
        next_month_start_at, _ = _local_day_bounds(next_month_start)

        booking_stats = Booking.objects.aggregate(
            total=Count("id"),
            confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
            pending=Count(
                "id",
                filter=Q(
                    status__in=[
                        Booking.Status.HELD,
                        Booking.Status.PAYMENT_PENDING,
                    ]
                ),
            ),
            expired=Count("id", filter=Q(status=Booking.Status.EXPIRED)),
            cancelled=Count("id", filter=Q(status=Booking.Status.CANCELLED)),
            refunded=Count("id", filter=Q(status=Booking.Status.REFUNDED)),
        )
        payment_stats = Payment.objects.aggregate(
            successful=Count("id", filter=Q(status=Payment.Status.SUCCEEDED)),
            pending=Count(
                "id",
                filter=Q(
                    status__in=[
                        Payment.Status.CREATING,
                        Payment.Status.PENDING,
                    ]
                ),
            ),
            failed=Count("id", filter=Q(status=Payment.Status.FAILED)),
            refunded=Count("id", filter=Q(status=Payment.Status.REFUNDED)),
        )
        revenue = Payment.objects.filter(
            status=Payment.Status.SUCCEEDED,
            booking__status=Booking.Status.CONFIRMED,
        ).aggregate(
            total=Sum("amount"),
            today=Sum(
                "amount",
                filter=Q(updated_at__gte=today_start, updated_at__lt=tomorrow_start),
            ),
            this_month=Sum(
                "amount",
                filter=Q(
                    updated_at__gte=month_start_at,
                    updated_at__lt=next_month_start_at,
                ),
            ),
        )
        ticket_stats = Ticket.objects.aggregate(
            issued=Count("id", filter=Q(status=Ticket.Status.ISSUED)),
            used=Count("id", filter=Q(status=Ticket.Status.USED)),
            cancelled=Count("id", filter=Q(status=Ticket.Status.CANCELLED)),
        )

        return Response({
            "bookings": booking_stats,
            "payments": payment_stats,
            "revenue": {
                key: str(value if value is not None else Decimal("0.00"))
                for key, value in revenue.items()
            },
            "tickets": ticket_stats,
            "events": {
                "total": Event.objects.count(),
                "upcoming": Event.objects.filter(starts_at__gte=now).count(),
            },
        })
