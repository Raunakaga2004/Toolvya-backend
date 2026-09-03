from django.contrib import admin

from .models import PDFJob


@admin.register(PDFJob)
class PDFJobAdmin(admin.ModelAdmin):
    list_display = ("id", "tool", "status", "input_count", "download_count", "created_at", "expires_at")
    list_filter = ("tool", "status", "created_at")
    search_fields = ("id", "error_message", "result_filename")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "expires_at",
        "download_count",
    )
