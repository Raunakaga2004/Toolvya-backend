import logging

from django.core.management.base import BaseCommand

from apps.pdf.tasks import cleanup_expired_pdf_jobs

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete expired PDF job files and mark jobs expired."

    def handle(self, *args, **options):
        logger.info("cleanup_pdf_jobs management command invoked")
        cleaned = cleanup_expired_pdf_jobs.apply().get()
        logger.info("cleanup_pdf_jobs management command finished: %s job(s) cleaned", cleaned)
        self.stdout.write(self.style.SUCCESS(f"Expired PDF jobs cleaned: {cleaned}"))
