"""Tandai peminjaman ACTIVE yang melewati due_date menjadi OVERDUE.

Jalankan manual:   python manage.py sync_overdue
Jadwalkan harian:  cron (Linux) / Task Scheduler (Windows), mis. setiap 00:05
"""

from django.core.management.base import BaseCommand

from apps.loans.services import sync_overdue_loans


class Command(BaseCommand):
    help = "Menandai peminjaman ACTIVE yang melewati jatuh tempo sebagai OVERDUE."

    def handle(self, *args, **options):
        updated = sync_overdue_loans()
        self.stdout.write(self.style.SUCCESS(f"{updated} peminjaman ditandai OVERDUE."))
