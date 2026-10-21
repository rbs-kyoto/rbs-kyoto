from django.conf import settings
from django.http import FileResponse


def service_worker(request):
    response = FileResponse(
        (settings.BASE_DIR / "static" / "service-worker.js").open("rb"),
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response
