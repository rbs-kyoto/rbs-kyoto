from django.conf import settings
from django.db import connection
from django.http import FileResponse, HttpResponse


def service_worker(request):
    response = FileResponse(
        (settings.BASE_DIR / "static" / "service-worker.js").open("rb"),
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


def healthz(request):
    """コンテナの健康チェック用。DBまで読めることを確かめる。"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response
