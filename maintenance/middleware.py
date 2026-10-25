from django.conf import settings
from django.shortcuts import render
from django.utils import timezone

from .models import MaintenanceSetting


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if (
            # 管理ホストはメンテ中こそ使うので止めない
            settings.SITE_ROLE == "admin"
            or path == "/admin"
            or path.startswith("/admin/")
            or path.startswith("/static/")
            or path.startswith("/media/")
            or path in {"/favicon.ico", "/robots.txt", "/service-worker.js", "/healthz/"}
        ):
            return self.get_response(request)

        setting = MaintenanceSetting.get_solo()
        status = setting.status_at(timezone.now())
        if status == MaintenanceSetting.Status.INACTIVE:
            return self.get_response(request)

        response = render(
            request,
            "maintenance/maintenance.html",
            {
                "maintenance": setting,
                "maintenance_status": status,
            },
            status=503,
        )
        response["Retry-After"] = "300"
        return response
