from django.apps import AppConfig


# 書き出し結果に影響するモデル。保存・削除されたら「未公開の変更あり」にする。
CONTENT_MODELS = (
    "main.Pickup",
    "main.Category",
    "main.News",
    "manuals.Manual",
    "video_archive.Video",
    "video_archive.VideoGroup",
)


def _mark_content_changed(sender, **kwargs):
    from .models import ContentRevision

    if kwargs.get("raw"):
        return
    ContentRevision.touch()


class PublisherConfig(AppConfig):
    name = 'publisher'
    verbose_name = "サイト公開"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_delete, post_save

        for label in CONTENT_MODELS:
            model = apps.get_model(label)
            post_save.connect(_mark_content_changed, sender=model, dispatch_uid=f"publisher-save-{label}")
            post_delete.connect(_mark_content_changed, sender=model, dispatch_uid=f"publisher-delete-{label}")
