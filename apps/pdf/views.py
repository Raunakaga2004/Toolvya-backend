from __future__ import annotations

import logging
import uuid

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiRequest, OpenApiResponse, OpenApiTypes, extend_schema

from apps.core.response import error_response, success_response

from .models import PDFJob
from .serializers import (
    CompressPDFJobCreateSerializer,
    MergePDFJobCreateSerializer,
    PDFJobSerializer,
    RemovePagesPDFJobCreateSerializer,
    ReorderPDFJobCreateSerializer,
    SplitPDFJobCreateSerializer,
)
from .services import (
    delete_job_storage,
    prepare_job_expiry,
    store_uploaded_files,
)
from .tasks import process_pdf_job

logger = logging.getLogger(__name__)


def get_job_or_404(job_id: str) -> PDFJob:
    """Look up a PDFJob by id, routing a malformed id through the same JSON
    404 as a well-formed-but-missing one (job_id is str in urls.py so that
    invalid UUIDs reach DRF's exception handler instead of Django's raw
    HTML 404)."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise Http404("No PDFJob matches the given query.")
    return get_object_or_404(PDFJob, pk=job_id)


class PDFToolBaseAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pdf_tools"

    serializer_class = None
    tool_name = None

    def build_response(self, job: PDFJob):
        serializer = PDFJobSerializer(job, context={"request": self.request})
        return success_response(serializer.data, http_status=status.HTTP_202_ACCEPTED)

    def create_job(self, *, files, params: dict | None = None) -> PDFJob:
        params = params or {}
        job = PDFJob.objects.create(
            tool=self.tool_name,
            params=params,
            input_count=len(files),
            expires_at=timezone.now(),
        )
        logger.info("Job %s (%s) created with %s input file(s)", job.id, self.tool_name, len(files))
        try:
            input_paths = store_uploaded_files(job, files)
            job.input_paths = input_paths
            job.save(update_fields=["input_paths", "input_count", "updated_at"])
            prepare_job_expiry(job)
            process_pdf_job.delay(str(job.id))
            job.refresh_from_db()
            return job
        except Exception:
            logger.exception("Job %s (%s) setup failed, rolling back", job.id, self.tool_name)
            delete_job_storage(job)
            job.delete()
            raise


class MergePDFAPIView(PDFToolBaseAPIView):
    serializer_class = MergePDFJobCreateSerializer
    tool_name = PDFJob.Tool.MERGE

    @extend_schema(
        request=OpenApiRequest(
            request=MergePDFJobCreateSerializer,
            encoding={"files": {"contentType": "application/pdf"}},
        ),
        responses=PDFJobSerializer,
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        files = serializer.validated_data["files"]
        job = self.create_job(files=files)
        return self.build_response(job)


class SplitPDFAPIView(PDFToolBaseAPIView):
    serializer_class = SplitPDFJobCreateSerializer
    tool_name = PDFJob.Tool.SPLIT

    @extend_schema(
        request=OpenApiRequest(
            request=SplitPDFJobCreateSerializer,
            encoding={"file": {"contentType": "application/pdf"}},
        ),
        responses=PDFJobSerializer,
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]
        job = self.create_job(files=[file], params={"ranges": serializer.validated_data.get("ranges", "")})
        return self.build_response(job)


class ReorderPDFAPIView(PDFToolBaseAPIView):
    serializer_class = ReorderPDFJobCreateSerializer
    tool_name = PDFJob.Tool.REORDER

    @extend_schema(
        request=OpenApiRequest(
            request=ReorderPDFJobCreateSerializer,
            encoding={"file": {"contentType": "application/pdf"}},
        ),
        responses=PDFJobSerializer,
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]
        job = self.create_job(files=[file], params={"order": serializer.validated_data["order"]})
        return self.build_response(job)


class RemovePagesPDFAPIView(PDFToolBaseAPIView):
    serializer_class = RemovePagesPDFJobCreateSerializer
    tool_name = PDFJob.Tool.REMOVE_PAGES

    @extend_schema(
        request=OpenApiRequest(
            request=RemovePagesPDFJobCreateSerializer,
            encoding={"file": {"contentType": "application/pdf"}},
        ),
        responses=PDFJobSerializer,
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]
        job = self.create_job(files=[file], params={"pages": serializer.validated_data["pages"]})
        return self.build_response(job)


class CompressPDFAPIView(PDFToolBaseAPIView):
    serializer_class = CompressPDFJobCreateSerializer
    tool_name = PDFJob.Tool.COMPRESS

    @extend_schema(
        request=OpenApiRequest(
            request=CompressPDFJobCreateSerializer,
            encoding={"file": {"contentType": "application/pdf"}},
        ),
        responses=PDFJobSerializer,
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]
        job = self.create_job(files=[file])
        return self.build_response(job)


class PDFJobDetailAPIView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pdf_tools"

    @extend_schema(responses=PDFJobSerializer)
    def get(self, request, job_id: str):
        job = get_job_or_404(job_id)
        if job.is_expired:
            job.mark_expired()
            delete_job_storage(job)
        logger.debug("Job %s status lookup: %s", job.id, job.status)
        serializer = PDFJobSerializer(job, context={"request": request})
        return success_response(serializer.data)


class PDFJobDownloadAPIView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pdf_tools"

    @extend_schema(
        responses={
            200: OpenApiResponse(response=OpenApiTypes.BINARY, description="Downloaded PDF or ZIP archive."),
            409: OpenApiResponse(description="Result is not ready."),
        }
    )
    def get(self, request, job_id: str):
        job = get_job_or_404(job_id)
        if job.is_expired:
            job.mark_expired()
            delete_job_storage(job)
            logger.info("Download rejected for job %s: expired", job.id)
            return error_response(
                "This job has expired and the files have been deleted. "
                "Please upload your files again to start a new job.",
                code="JOB_EXPIRED",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if job.status != PDFJob.Status.COMPLETED or not job.output_file or not job.output_file.exists():
            logger.info("Download rejected for job %s: not ready (status=%s)", job.id, job.status)
            return error_response(
                "Your PDF is still being processed. "
                "Please check again in a few moments.",
                code="RESULT_NOT_READY",
                http_status=status.HTTP_409_CONFLICT,
            )
        job.download_count = job.download_count + 1
        job.save(update_fields=["download_count", "updated_at"])
        logger.info("Job %s downloaded (count=%s)", job.id, job.download_count)
        content_type = "application/zip" if job.result_filename.endswith(".zip") else "application/pdf"
        return FileResponse(open(job.output_file, "rb"), as_attachment=True, filename=job.result_filename, content_type=content_type)
