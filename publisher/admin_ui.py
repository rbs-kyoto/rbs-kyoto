"""管理画面（Unfold）に差し込む部品。"""

from django.urls import reverse

from . import builder


def unpublished_badge(request):
    return "未公開" if builder.has_unpublished_changes() else None


class LivePreviewMixin:
    """編集画面の右側に、入力中の内容で描画したサイトのプレビューを出す。

    publisher/live_preview.py の PREVIEWS に登録したモデルで使う。
    """

    change_form_template = "publisher/live_preview_change_form.html"

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        opts = self.model._meta
        context["live_preview_url"] = reverse("publisher:live_preview", args=[opts.app_label, opts.model_name])
        context["live_preview_object_id"] = obj.pk if obj is not None else ""
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)
