from __future__ import annotations

import io
import logging
import re
import shutil
import zipfile
from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from .models import PDFJob

logger = logging.getLogger(__name__)

PAGE_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


def validation_message(exc: ValidationError) -> str:
    """Django's ValidationError.__str__ always renders as repr(list(...)),
    e.g. '["File is invalid."]'. Use the actual message text instead."""
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@dataclass(frozen=True)
class SplitChunk:
    start: int
    end: int


def validate_uploaded_pdf(uploaded_file: UploadedFile) -> None:
    filename = uploaded_file.name or "unknown"
    logger.debug("Validating uploaded file '%s' (%s bytes)", filename, uploaded_file.size)

    if uploaded_file.size <= 0:
        logger.warning("Rejected upload '%s': empty file", filename)
        raise ValidationError(
            f"The file '{filename}' is empty. Please upload a valid PDF."
        )

    if uploaded_file.size > settings.PDF_MAX_INPUT_BYTES:
        max_mb = settings.PDF_MAX_INPUT_BYTES // (1024 * 1024)
        logger.warning("Rejected upload '%s': exceeds %sMB limit", filename, max_mb)
        raise ValidationError(
            f"File '{filename}' exceeds the maximum size of {max_mb}MB. "
            f"Please upload a smaller file."
        )

    if not filename.lower().endswith(".pdf"):
        logger.warning("Rejected upload '%s': not a .pdf file", filename)
        raise ValidationError(
            f"Only PDF files are accepted. You uploaded '{filename}'. "
            f"Please upload a PDF file."
        )

    try:
        reader = PdfReader(uploaded_file, strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            logger.warning("Rejected upload '%s': password protected", filename)
            raise ValidationError(
                "Password-protected PDFs are not supported. "
                "Please upload a PDF without password protection."
            )
        if len(reader.pages) == 0:
            logger.warning("Rejected upload '%s': zero pages", filename)
            raise ValidationError(
                f"The PDF file '{filename}' has no pages. "
                f"Please upload a valid PDF."
            )
        uploaded_file.seek(0)
    except ValidationError:
        raise
    except Exception:
        logger.exception("Rejected upload '%s': failed to parse as PDF", filename)
        raise ValidationError(
            f"The file '{filename}' is not a valid PDF. It may be corrupted. "
            f"Please try uploading again."
        )


def uploaded_pdf_page_count(uploaded_file: UploadedFile) -> int:
    validate_uploaded_pdf(uploaded_file)
    reader = PdfReader(uploaded_file, strict=False)
    count = len(reader.pages)
    uploaded_file.seek(0)
    return count


def parse_page_ranges(value: str, total_pages: int) -> list[SplitChunk]:
    cleaned = (value or "").strip()
    if not cleaned:
        return [SplitChunk(i, i) for i in range(1, total_pages + 1)]

    chunks: list[SplitChunk] = []
    for raw_chunk in cleaned.split(","):
        token = raw_chunk.strip()
        if not token:
            continue
        match = PAGE_RANGE_RE.match(token)
        if not match:
            raise ValidationError(
                f"Invalid page range '{token}'. "
                f"Use format like '1-3' or '1-3, 5-7'."
            )
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < 1 or start > end:
            raise ValidationError(
                f"Invalid page range '{token}'. "
                f"Use format like '1-3' or '1-3, 5-7'."
            )
        if end > total_pages:
            raise ValidationError(
                f"Page range '{token}' exceeds the document's {total_pages} pages. "
                f"Please enter a valid range."
            )
        chunks.append(SplitChunk(start, end))
    if not chunks:
        raise ValidationError(
            "Please provide at least one valid page range (e.g., '1-3')."
        )
    return chunks


def parse_page_order(value: str, total_pages: int) -> list[int]:
    try:
        order = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise ValidationError(
            "Page order must contain only numbers separated by commas "
            "(e.g., '3, 1, 2')."
        ) from exc
    if len(order) != total_pages:
        raise ValidationError(
            f"Page order must include all {total_pages} pages exactly once. "
            f"You provided {len(order)} page(s)."
        )
    if sorted(order) != list(range(1, total_pages + 1)):
        raise ValidationError(
            f"Page order must include all pages from 1 to {total_pages} "
            f"with no duplicates or missing pages."
        )
    return order


def job_root(job: PDFJob) -> Path:
    return job.root_dir


def ensure_job_directories(job: PDFJob) -> None:
    job.input_dir.mkdir(parents=True, exist_ok=True)
    job.output_dir.mkdir(parents=True, exist_ok=True)


def store_uploaded_files(job: PDFJob, uploaded_files: list[UploadedFile]) -> list[str]:
    ensure_job_directories(job)
    relative_paths: list[str] = []
    for index, uploaded_file in enumerate(uploaded_files, start=1):
        validate_uploaded_pdf(uploaded_file)
        safe_name = Path(uploaded_file.name).name or f"input-{index}.pdf"
        stored_name = f"{index:02d}-{safe_name}"
        absolute_path = job.input_dir / stored_name
        with open(absolute_path, "wb") as handle:
            for chunk in uploaded_file.chunks():
                handle.write(chunk)
        relative_paths.append(job.storage_relative_path(absolute_path))
    logger.info("Job %s: stored %s input file(s)", job.id, len(relative_paths))
    return relative_paths


def absolute_paths(relative_paths: list[str]) -> list[Path]:
    return [Path(settings.MEDIA_ROOT) / relative_path for relative_path in relative_paths]


def get_reader(path: Path) -> PdfReader:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValidationError(
                "Password-protected PDFs are not supported. "
                "Please upload a PDF without password protection."
            )
        if len(reader.pages) == 0:
            raise ValidationError(
                "The PDF file has no pages. Please upload a valid PDF."
            )
        if len(reader.pages) > settings.PDF_MAX_PAGES:
            raise ValidationError(
                f"The PDF has too many pages. "
                f"Maximum allowed is {settings.PDF_MAX_PAGES} pages."
            )
        return reader
    except ValidationError:
        raise
    except Exception as exc:
        logger.exception("Failed to read PDF '%s'", path)
        raise ValidationError(
            f"Could not read '{path.name}'. The file may be corrupted. "
            f"Please try again."
        ) from exc


def merge_pdfs(input_paths: list[Path], output_path: Path) -> int:
    writer = PdfWriter()
    total_pages = 0
    for path in input_paths:
        reader = get_reader(path)
        for page in reader.pages:
            writer.add_page(page)
            total_pages += 1
    writer.add_metadata({"/Producer": "Toolvaya"})
    with open(output_path, "wb") as handle:
        writer.write(handle)
    logger.debug("Merged %s file(s) into %s (%s pages)", len(input_paths), output_path, total_pages)
    return total_pages


def compress_pdf(input_path: Path, output_path: Path) -> int:
    reader = get_reader(input_path)
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    if reader.metadata:
        writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
    with open(output_path, "wb") as handle:
        writer.write(handle)
    logger.debug("Compressed %s (%s pages) -> %s", input_path, len(reader.pages), output_path)
    return len(reader.pages)


def read_page_count(input_path: Path) -> int:
    return len(get_reader(input_path).pages)


def reorder_pdf(input_path: Path, output_path: Path, page_order: list[int]) -> int:
    reader = get_reader(input_path)
    writer = PdfWriter()
    for page_number in page_order:
        writer.add_page(reader.pages[page_number - 1])
    if reader.metadata:
        writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
    with open(output_path, "wb") as handle:
        writer.write(handle)
    logger.debug("Reordered %s -> %s (%s pages)", input_path, output_path, len(page_order))
    return len(page_order)


def remove_pages(input_path: Path, output_path: Path, pages_to_remove: set[int]) -> int:
    reader = get_reader(input_path)
    writer = PdfWriter()
    kept = 0
    for page_number, page in enumerate(reader.pages, start=1):
        if page_number in pages_to_remove:
            continue
        writer.add_page(page)
        kept += 1
    if kept == 0:
        logger.warning("Remove-pages on %s would leave an empty PDF", input_path)
        raise ValidationError(
            "Removing these pages would leave an empty PDF. "
            "Please keep at least one page."
        )
    if reader.metadata:
        writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
    with open(output_path, "wb") as handle:
        writer.write(handle)
    logger.debug("Removed %s page(s) from %s -> %s (%s kept)", len(pages_to_remove), input_path, output_path, kept)
    return kept


def split_pdf(input_path: Path, output_zip_path: Path, chunks: list[SplitChunk]) -> int:
    reader = get_reader(input_path)
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    total_pages = 0
    with zipfile.ZipFile(output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, chunk in enumerate(chunks, start=1):
            writer = PdfWriter()
            for page_number in range(chunk.start, chunk.end + 1):
                writer.add_page(reader.pages[page_number - 1])
                total_pages += 1
            buffer = io.BytesIO()
            writer.write(buffer)
            filename = f"split-{index:03d}-{chunk.start}-{chunk.end}.pdf"
            archive.writestr(filename, buffer.getvalue())
    logger.debug("Split %s into %s chunk(s) -> %s (%s pages)", input_path, len(chunks), output_zip_path, total_pages)
    return total_pages


def build_output_filename(job: PDFJob, *, suffix: str) -> str:
    return f"{job.tool}-{job.id}{suffix}"


def create_output_path(job: PDFJob, *, suffix: str) -> Path:
    ensure_job_directories(job)
    output_path = job.output_dir / build_output_filename(job, suffix=suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def prepare_job_expiry(job: PDFJob) -> None:
    job.expires_at = timezone.now() + timedelta(hours=settings.PDF_JOB_TTL_HOURS)
    job.save(update_fields=["expires_at", "updated_at"])


def delete_job_storage(job: PDFJob) -> None:
    shutil.rmtree(job.root_dir, ignore_errors=True)
    logger.debug("Job %s: deleted storage at %s", job.id, job.root_dir)
