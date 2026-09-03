from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from .models import PDFJob
from .services import (
    parse_page_order,
    parse_page_ranges,
    uploaded_pdf_page_count,
    validate_uploaded_pdf,
    validation_message,
)


class MergePDFJobCreateSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(
            help_text="Upload a PDF file.",
            error_messages={
                "required": "Please upload a PDF file.",
                "invalid": "Invalid file. Please upload a PDF file.",
            },
        ),
        min_length=2,
        help_text="Upload two or more PDF files.",
        error_messages={
            "min_length": "Please upload at least 2 PDF files to merge.",
            "required": "Please upload at least 2 PDF files to merge.",
        },
    )

    def validate_files(self, value):
        if len(value) > settings.PDF_MAX_INPUT_FILES:
            raise serializers.ValidationError(
                f"Too many files. You can upload up to {settings.PDF_MAX_INPUT_FILES} files at once."
            )
        for uploaded_file in value:
            try:
                validate_uploaded_pdf(uploaded_file)
            except Exception as exc:
                raise serializers.ValidationError(validation_message(exc))
        return value


class SplitPDFJobCreateSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="Upload a PDF file.",
        error_messages={
            "required": "Please upload a PDF file to split.",
            "invalid": "Invalid file. Please upload a PDF file.",
        },
    )
    ranges = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Page ranges to split (e.g., '1-3, 4-6'). Leave empty to split into individual pages.",
    )

    def validate_ranges(self, value):
        return value or ""

    def validate(self, attrs):
        try:
            validate_uploaded_pdf(attrs["file"])
        except Exception as exc:
            raise serializers.ValidationError({"file": validation_message(exc)})
        page_count = uploaded_pdf_page_count(attrs["file"])
        try:
            parse_page_ranges(attrs.get("ranges", ""), page_count)
        except Exception as exc:
            raise serializers.ValidationError({"ranges": validation_message(exc)})
        return attrs


class ReorderPDFJobCreateSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="Upload a PDF file.",
        error_messages={
            "required": "Please upload a PDF file to reorder.",
            "invalid": "Invalid file. Please upload a PDF file.",
        },
    )
    order = serializers.CharField(
        help_text="Page order as comma-separated numbers (e.g., '3, 1, 2').",
        error_messages={
            "required": "Please provide the page order.",
            "blank": "Please provide the page order (e.g., '3, 1, 2').",
        },
    )

    def validate(self, attrs):
        try:
            validate_uploaded_pdf(attrs["file"])
        except Exception as exc:
            raise serializers.ValidationError({"file": validation_message(exc)})
        page_count = uploaded_pdf_page_count(attrs["file"])
        try:
            parse_page_order(attrs["order"], page_count)
        except Exception as exc:
            raise serializers.ValidationError({"order": validation_message(exc)})
        return attrs


class RemovePagesPDFJobCreateSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="Upload a PDF file.",
        error_messages={
            "required": "Please upload a PDF file.",
            "invalid": "Invalid file. Please upload a PDF file.",
        },
    )
    pages = serializers.CharField(
        help_text="Pages to remove (e.g., '2, 4-6').",
        error_messages={
            "required": "Please specify which pages to remove.",
            "blank": "Please specify which pages to remove (e.g., '2, 4-6').",
        },
    )

    def validate(self, attrs):
        try:
            validate_uploaded_pdf(attrs["file"])
        except Exception as exc:
            raise serializers.ValidationError({"file": validation_message(exc)})
        page_count = uploaded_pdf_page_count(attrs["file"])
        try:
            chunks = parse_page_ranges(attrs["pages"], page_count)
        except Exception as exc:
            raise serializers.ValidationError({"pages": validation_message(exc)})
        pages_to_remove = {page for chunk in chunks for page in range(chunk.start, chunk.end + 1)}
        if len(pages_to_remove) >= page_count:
            raise serializers.ValidationError(
                {"pages": "You can't remove every page. Please keep at least one page."}
            )
        return attrs


class CompressPDFJobCreateSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="Upload a PDF file to compress.",
        error_messages={
            "required": "Please upload a PDF file to compress.",
            "invalid": "Invalid file. Please upload a PDF file.",
        },
    )

    def validate_file(self, value):
        try:
            validate_uploaded_pdf(value)
        except Exception as exc:
            raise serializers.ValidationError(validation_message(exc))
        return value


class PDFJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    status_url = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = PDFJob
        fields = [
            "id",
            "tool",
            "status",
            "input_count",
            "page_count",
            "result_filename",
            "error_message",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "expires_at",
            "download_count",
            "download_url",
            "status_url",
            "is_expired",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        request = self.context.get("request")
        if obj.status != PDFJob.Status.COMPLETED or not obj.output_path:
            return None
        return request.build_absolute_uri(f"/api/pdf/jobs/{obj.id}/download/") if request else f"/api/pdf/jobs/{obj.id}/download/"

    def get_status_url(self, obj):
        request = self.context.get("request")
        url = f"/api/pdf/jobs/{obj.id}/"
        return request.build_absolute_uri(url) if request else url
