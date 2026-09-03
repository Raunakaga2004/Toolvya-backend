from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response


def success_response(data, http_status=status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=http_status)


def error_response(
    message: str,
    code: str = "ERROR",
    details=None,
    http_status=status.HTTP_400_BAD_REQUEST,
) -> Response:
    body = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        body["error"]["details"] = details
    return Response(body, status=http_status)
