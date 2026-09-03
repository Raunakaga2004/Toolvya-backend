from rest_framework.decorators import api_view

from apps.core.response import success_response


@api_view(["GET"])
def home(_request):
    return success_response({
        "service": "toolvaya-backend",
        "status": "ok",
        "version": "0.1.0",
    })


@api_view(["GET"])
def health_check(_request):
    return success_response({"status": "ok"})
