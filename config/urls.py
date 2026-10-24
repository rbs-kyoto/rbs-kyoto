from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from errors import views as error_views
from . import views as config_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("deploy/", include("publisher.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    path("accounts/", include("accounts.urls")),
    path("service-worker.js", config_views.service_worker, name="service_worker"),
    path("418/", error_views.teapot, name="teapot"),
    path("preview_400/", error_views.preview_400, name="preview_400"),
    path("preview_403/", error_views.preview_403, name="preview_403"),
    path("preview_404/", error_views.preview_404, name="preview_404"),
    path("preview_500/", error_views.preview_500, name="preview_500"),
    path("preview_513/", error_views.preview_513, name="preview_513"),
    path("preview_418/", error_views.preview_418, name="preview_418"),
    path("manuals/", include("manuals.urls")),
    path("videos/", include("video_archive.urls")),
    path("", include("main.urls")),
    path("accounts/", include("allauth.urls")),
]

handler400 = "errors.views.bad_request"
handler403 = "errors.views.permission_denied"
handler404 = "errors.views.page_not_found"
handler500 = "errors.views.server_error"

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )