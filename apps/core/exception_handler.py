from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def core_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        code = _code_from_status(response.status_code)
        message = _extract_message(response.data)
        details = _extract_details(response.data)

        body = {
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if details:
            body["error"]["details"] = details

        response.data = body

        request = context.get("request")
        view = context.get("view")
        log_level = logging.ERROR if response.status_code >= 500 else logging.WARNING
        logger.log(
            log_level,
            "API error %s [%s] on %s %s in %s: %s",
            response.status_code,
            code,
            getattr(request, "method", "-"),
            getattr(request, "path", "-"),
            type(view).__name__ if view else "-",
            message,
        )
    else:
        logger.exception("Unhandled exception in %s", type(context.get("view")).__name__ if context.get("view") else "-")
    return response


def _code_from_status(status_code: int) -> str:
    mapping = {
        400: "VALIDATION_ERROR",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        429: "THROTTLED",
        500: "SERVER_ERROR",
    }
    return mapping.get(status_code, "ERROR")


def _extract_message(data) -> str:
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        if "non_field_errors" in data:
            errors = data["non_field_errors"]
            if isinstance(errors, list) and errors:
                return str(errors[0])
    if isinstance(data, list) and data:
        return str(data[0])
    return "Invalid request."


def _extract_details(data):
    if not isinstance(data, dict):
        return None

    details = {}
    for key, value in data.items():
        if key in ("detail", "non_field_errors"):
            continue
        if isinstance(value, list):
            details[key] = [str(item) if not isinstance(item, str) else item for item in value]
        elif isinstance(value, dict):
            details[key] = value
        else:
            details[key] = [str(value)]

    return details if details else None
