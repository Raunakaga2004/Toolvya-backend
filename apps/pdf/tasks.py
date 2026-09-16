from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader

from .models import PDFJob
from .services import (
    absolute_paths,
    compress_pdf,
    create_output_path,
    merge_pdfs,
    parse_page_order,
    parse_page_ranges,
    read_page_count,
    remove_pages,
    reorder_pdf,
    split_pdf,
)

logger = logging.getLogger(__name__)


def _load_job(job_id) -> PDFJob:
    return PDFJob.objects.get(pk=job_id)


@shared_task(bind=True, ignore_result=True)
def process_pdf_job(self, job_id: str) -> None:
    logger.info("Task process_pdf_job received for job %s", job_id)
    job = _load_job(job_id)
    if job.status not in {PDFJob.Status.PENDING, PDFJob.Status.PROCESSING}:
        logger.warning("Job %s already in status %s, skipping", job.id, job.status)
        return

    try:
        job.mark_processing()
        input_paths = absolute_paths(job.input_paths)
        if job.tool == PDFJob.Tool.MERGE:
            output_path = create_output_path(job, suffix=".pdf")
            page_count = merge_pdfs(input_paths, output_path)
            job.mark_completed(
                output_path=output_path,
                result_filename=output_path.name,
                page_count=page_count,
            )
        elif job.tool == PDFJob.Tool.COMPRESS:
            output_path = create_output_path(job, suffix=".pdf")
            page_count = compress_pdf(input_paths[0], output_path)
            job.mark_completed(
                output_path=output_path,
                result_filename=output_path.name,
                page_count=page_count,
            )
        elif job.tool == PDFJob.Tool.REORDER:
            page_count = read_page_count(input_paths[0])
            order = parse_page_order(job.params["order"], page_count)
            output_path = create_output_path(job, suffix=".pdf")
            page_count = reorder_pdf(input_paths[0], output_path, order)
            job.mark_completed(
                output_path=output_path,
                result_filename=output_path.name,
                page_count=page_count,
            )
        elif job.tool == PDFJob.Tool.REMOVE_PAGES:
            page_count = read_page_count(input_paths[0])
            chunks = parse_page_ranges(job.params["pages"], page_count)
            pages_to_remove = {page for chunk in chunks for page in range(chunk.start, chunk.end + 1)}
            output_path = create_output_path(job, suffix=".pdf")
            page_count = remove_pages(input_paths[0], output_path, pages_to_remove)
            job.mark_completed(
                output_path=output_path,
                result_filename=output_path.name,
                page_count=page_count,
            )
        elif job.tool == PDFJob.Tool.SPLIT:
            output_path = create_output_path(job, suffix=".zip")
            reader = PdfReader(str(input_paths[0]), strict=False)
            chunks = parse_page_ranges(job.params.get("ranges", ""), len(reader.pages))
            page_count = split_pdf(input_paths[0], output_path, chunks)
            job.mark_completed(
                output_path=output_path,
                result_filename=output_path.name,
                page_count=page_count,
            )
        else:
            raise ValueError(f"Unsupported PDF tool '{job.tool}'.")
    except Exception as exc:  # pragma: no cover - task safety
        logger.exception("Job %s (%s) processing failed", job.id, job.tool)
        job.mark_failed(str(exc))
        raise
    else:
        logger.info("Task process_pdf_job finished for job %s", job_id)


@shared_task(bind=True, ignore_result=True)
def cleanup_expired_pdf_jobs(self) -> int:
    logger.info("Task cleanup_expired_pdf_jobs started")
    now = timezone.now()
    expired_jobs = PDFJob.objects.filter(expires_at__lte=now).exclude(status=PDFJob.Status.EXPIRED)[: settings.PDF_CLEANUP_BATCH_SIZE]
    expired_ids: list[str] = []
    for job in expired_jobs:
        job.mark_expired()
        job.clear_storage()
        expired_ids.append(str(job.id))
    logger.info("Task cleanup_expired_pdf_jobs finished: %s job(s) expired", len(expired_ids))
    return len(expired_ids)
