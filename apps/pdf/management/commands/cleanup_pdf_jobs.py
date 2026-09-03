from django.core.management.base import BaseCommand

from apps.pdf.tasks import cleanup_expired_pdf_jobs


class Command(BaseCommand):
    help = "Delete expired PDF job files and mark jobs expired."

    def handle(self, *args, **options):
        cleaned = cleanup_expired_pdf_jobs.apply().get()
        self.stdout.write(self.style.SUCCESS(f"Expired PDF jobs cleaned: {cleaned}"))
