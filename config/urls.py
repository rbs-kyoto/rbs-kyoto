from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import include, path
from django_ckeditor_5 import views as ckeditor_views
from accounts.decorators import club_editor_required
from errors import views as error_views
from . import views as config_views


def admin_login(request, extra_context=None):
    """管理画面には専用のログイン画面を置かず、サイトのログイン画面を通す。

    パスワードを試せる入口を1つにして、失敗回数の制限を必ず通るようにするため。
    """
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if request.user.is_active and request.user.is_staff:
        return redirect("admin:index")
    raise PermissionDenied


admin.site.login = admin_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "ckeditor5/image_upload/",
        club_editor_required(ckeditor_views.upload_file),
        name="ck_editor_5_upload_file",
    ),
    path("accounts/", include("accounts.urls")),
    path("equipment/", include("equipment.urls")),
    path("roll/", include("roll.urls")),
    path("manifest.webmanifest", config_views.web_manifest, name="web_manifest"),
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
    path("schedule/", include("schedule.urls")),
    path("places/", include("places.urls")),
    path("api/places/", include("places.api_urls")),
    path("", include("main.urls")),
    path("accounts/", include("allauth.urls")),
    path(
        "__beon__/",
        include("beon.urls", namespace="beon"),
    ),
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