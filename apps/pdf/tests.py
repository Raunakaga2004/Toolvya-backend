from __future__ import annotations

import io
import zipfile
from urllib.parse import urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from pypdf import PdfReader, PdfWriter
from rest_framework.test import APIClient

from .models import PDFJob


def make_pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_upload(name: str, page_count: int) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, make_pdf_bytes(page_count), content_type="application/pdf")


class PDFToolApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_merge_creates_downloadable_pdf(self) -> None:
        response = self.client.post(
            "/api/pdf/merge/",
            {"files": [make_upload("one.pdf", 1), make_upload("two.pdf", 2)]},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202)
        job = PDFJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, PDFJob.Status.COMPLETED)
        self.assertEqual(job.page_count, 3)

        download = self.client.get(urlparse(response.data["data"]["download_url"]).path)
        self.assertEqual(download.status_code, 200)
        pdf = PdfReader(io.BytesIO(b"".join(download.streaming_content)))
        self.assertEqual(len(pdf.pages), 3)

    def test_reorder_rebuilds_page_order(self) -> None:
        response = self.client.post(
            "/api/pdf/reorder/",
            {"file": make_upload("input.pdf", 3), "order": "3,1,2"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202)
        job = PDFJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, PDFJob.Status.COMPLETED)
        self.assertEqual(job.page_count, 3)

    def test_remove_pages_drops_selected_pages(self) -> None:
        response = self.client.post(
            "/api/pdf/remove-pages/",
            {"file": make_upload("input.pdf", 4), "pages": "2,4"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202)
        job = PDFJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, PDFJob.Status.COMPLETED)
        self.assertEqual(job.page_count, 2)

    def test_remove_all_pages_is_rejected(self) -> None:
        response = self.client.post(
            "/api/pdf/remove-pages/",
            {"file": make_upload("input.pdf", 2), "pages": "1-2"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_compress_returns_pdf_result(self) -> None:
        response = self.client.post(
            "/api/pdf/compress/",
            {"file": make_upload("input.pdf", 2)},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202)
        job = PDFJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, PDFJob.Status.COMPLETED)
        self.assertTrue(job.result_filename.endswith(".pdf"))

    def test_split_returns_zip_archive(self) -> None:
        response = self.client.post(
            "/api/pdf/split/",
            {"file": make_upload("input.pdf", 4), "ranges": "1-2,3-4"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202)
        job = PDFJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, PDFJob.Status.COMPLETED)
        download = self.client.get(urlparse(response.data["data"]["download_url"]).path)
        self.assertEqual(download.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(b"".join(download.streaming_content)))
        self.assertEqual(len(archive.namelist()), 2)

    def test_invalid_file_error_message_is_not_a_stringified_list(self) -> None:
        # Regression: django ValidationError.__str__() renders as repr(list(...)),
        # so a naive str(exc) leaked as e.g. '["Only PDF files are accepted..."]'.
        response = self.client.post(
            "/api/pdf/compress/",
            {"file": SimpleUploadedFile("input.txt", b"not a pdf", content_type="text/plain")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        message = response.data["error"]["details"]["file"][0]
        self.assertFalse(message.startswith("["))

    def test_job_detail_exposes_status(self) -> None:
        response = self.client.post(
            "/api/pdf/merge/",
            {"files": [make_upload("one.pdf", 1), make_upload("two.pdf", 1)]},
            format="multipart",
        )
        job_id = response.data["data"]["id"]
        detail = self.client.get(f"/api/pdf/jobs/{job_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["status"], PDFJob.Status.COMPLETED)
