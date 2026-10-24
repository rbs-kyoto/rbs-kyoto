"""管理ホスト（SITE_ROLE=admin）用のURL。

公開サイトのページは静的に書き出して Apache + gate/ が配信するので、ここには
Django管理画面とデプロイ管理だけを置く。
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_url = "/deploy/"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="publisher:dashboard", permanent=False)),
    path("admin/", admin.site.urls),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    path("deploy/", include("publisher.urls")),
]

# エラーテンプレートは公開側のURLを参照するので、公開側のURL設定で描画する
handler400 = "publisher.views.bad_request"
handler403 = "publisher.views.permission_denied"
handler404 = "publisher.views.page_not_found"
handler500 = "publisher.views.server_error"

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
