from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class PDFJob(models.Model):
    class Tool(models.TextChoices):
        MERGE = "merge", "Merge"
        SPLIT = "split", "Split"
        COMPRESS = "compress", "Compress"
        REORDER = "reorder", "Reorder"
        REMOVE_PAGES = "remove_pages", "Remove pages"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tool = models.CharField(max_length=16, choices=Tool.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    input_paths = models.JSONField(default=list, blank=True)
    params = models.JSONField(default=dict, blank=True)
    output_path = models.CharField(max_length=512, blank=True, default="")
    result_filename = models.CharField(max_length=255, blank=True, default="")
    input_count = models.PositiveIntegerField(default=0)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tool", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.tool}:{self.id}"

    @property
    def root_dir(self) -> Path:
        return Path(settings.MEDIA_ROOT) / "pdf_jobs" / str(self.id)

    @property
    def input_dir(self) -> Path:
        return self.root_dir / "inputs"

    @property
    def output_dir(self) -> Path:
        return self.root_dir / "output"

    @property
    def output_file(self) -> Path | None:
        if not self.output_path:
            return None
        return Path(settings.MEDIA_ROOT) / self.output_path

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def storage_relative_path(self, absolute_path: Path) -> str:
        return absolute_path.relative_to(settings.MEDIA_ROOT).as_posix()

    def mark_processing(self) -> None:
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])
        logger.info("Job %s (%s) started processing", self.id, self.tool)

    def mark_completed(self, *, output_path: Path, result_filename: str, page_count: int | None) -> None:
        self.status = self.Status.COMPLETED
        self.output_path = self.storage_relative_path(output_path)
        self.result_filename = result_filename
        self.page_count = page_count
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "output_path", "result_filename", "page_count", "completed_at", "updated_at"])
        logger.info("Job %s (%s) completed: %s pages -> %s", self.id, self.tool, page_count, result_filename)

    def mark_failed(self, message: str) -> None:
        self.status = self.Status.FAILED
        self.error_message = message[:4000]
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        logger.error("Job %s (%s) failed: %s", self.id, self.tool, message)

    def mark_expired(self) -> None:
        self.status = self.Status.EXPIRED
        self.save(update_fields=["status", "updated_at"])
        logger.info("Job %s (%s) marked expired", self.id, self.tool)

    def clear_storage(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)
        logger.debug("Job %s storage cleared at %s", self.id, self.root_dir)

