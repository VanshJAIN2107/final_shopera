"""
Cancel online-payment orders that were never paid.

    python manage.py cancel_stale_orders            (older than 24 hours)
    python manage.py cancel_stale_orders --hours 6

Run it daily (cron / scheduler). No stock is touched because stock is only taken
when a payment succeeds, and no customer emails are sent.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from app.models import Order


class Command(BaseCommand):
    help = 'Cancel unpaid Razorpay orders older than N hours.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options['hours'])

        count = Order.objects.filter(
            payment_method='RAZORPAY',
            payment_status__in=['Pending', 'Failed'],
            status='Pending',
            created_at__lt=cutoff,
        ).update(status='Cancelled', admin_note='Payment was never completed.')

        self.stdout.write(self.style.SUCCESS(f'Cancelled {count} unpaid order(s).'))
