from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """Logs every request/response with method, path, status, duration and user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000
        user = getattr(request, "user", None)
        user_display = user.pk if user is not None and getattr(user, "is_authenticated", False) else "anonymous"
        logger.info(
            "%s %s -> %s (%.1fms) user=%s ip=%s",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
            user_display,
            request.META.get("REMOTE_ADDR", "-"),
        )
        return response

    def process_exception(self, request, exception):
        logger.exception(
            "Unhandled exception on %s %s",
            request.method,
            request.get_full_path(),
        )
        return None
