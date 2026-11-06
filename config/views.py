from io import BytesIO
import json

from django.conf import settings
from django.http import FileResponse, HttpResponse


def service_worker(_request):
    icon_suffix = "-dev" if settings.DEBUG else ""
    script = (settings.BASE_DIR / "static" / "service-worker.js").read_text(
        encoding="utf-8"
    )
    script = script.replace("__PWA_ICON_SUFFIX__", icon_suffix)
    response = FileResponse(
        BytesIO(script.encode("utf-8")),
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


def web_manifest(_request):
    manifest_path = settings.BASE_DIR / "static" / "main" / "manifest.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    icon_suffix = "-dev" if settings.DEBUG else ""
    for icon in manifest["icons"]:
        icon_name = icon["src"].rsplit("/", 1)[-1]
        if icon_name.startswith("pwa-icon"):
            icon_name = icon_name.replace("pwa-icon", f"pwa-icon{icon_suffix}", 1)
            icon["src"] = f"/static/main/img/{icon_name}"

    response = HttpResponse(
        json.dumps(manifest, ensure_ascii=False),
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "no-cache"
    return response
