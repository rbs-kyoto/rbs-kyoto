
from django.contrib import admin
from django.urls import include, path

from config import views as config_views
from errors import views as error_views


urlpatterns = [
    # BeON
    path("", include("beon.urls", namespace="beon")),

    # 管理画面
    path("admin/", admin.site.urls),

    # 各アプリケーション
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    path("equipment/", include("equipment.urls")),
    path("roll/", include("roll.urls")),
    path("manuals/", include("manuals.urls")),
    path("videos/", include("video_archive.urls")),
    path("schedule/", include("schedule.urls")),
    path("places/", include("places.urls")),
    path("api/places/", include("places.api_urls")),

    # PWA
    path(
        "manifest.webmanifest",
        config_views.web_manifest,
        name="web_manifest",
    ),
    path(
        "service-worker.js",
        config_views.service_worker,
        name="service_worker",
    ),

    # エラーページ
    path("418/", error_views.teapot, name="teapot"),
    path("preview_400/", error_views.preview_400, name="preview_400"),
    path("preview_403/", error_views.preview_403, name="preview_403"),
    path("preview_404/", error_views.preview_404, name="preview_404"),
    path("preview_500/", error_views.preview_500, name="preview_500"),
    path("preview_513/", error_views.preview_513, name="preview_513"),
    path("preview_418/", error_views.preview_418, name="preview_418"),

    # メインサイトのURL（最後に配置）
    path("", include("main.urls")),
]
