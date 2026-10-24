from django.conf import settings
from django.db import models
from django.utils import timezone


class Deployment(models.Model):
    class Status(models.TextChoices):
        BUILDING = "building", "書き出し中"
        READY = "ready", "完了"
        FAILED = "failed", "失敗"

    version = models.PositiveIntegerField("バージョン", unique=True)
    description = models.CharField("説明", max_length=200, blank=True)
    status = models.CharField(
        "状態",
        max_length=16,
        choices=Status.choices,
        default=Status.BUILDING,
    )
    created_at = models.DateTimeField("作成日時", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="作成者",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    page_count = models.PositiveIntegerField("ページ数", default=0)
    error = models.TextField("エラー", blank=True)

    class Meta:
        ordering = ["-version"]
        verbose_name = "デプロイ"
        verbose_name_plural = "デプロイ"

    def __str__(self):
        return f"バージョン {self.version}"


class ContentRevision(models.Model):
    """公開対象のデータが最後に変わった日時。「未公開の変更あり」の判定に使う。"""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    changed_at = models.DateTimeField("最終更新日時", default=timezone.now)

    class Meta:
        verbose_name = "コンテンツ更新日時"
        verbose_name_plural = "コンテンツ更新日時"

    @classmethod
    def touch(cls):
        cls.objects.update_or_create(pk=1, defaults={"changed_at": timezone.now()})

    @classmethod
    def last_changed_at(cls):
        revision = cls.objects.filter(pk=1).first()
        return revision.changed_at if revision else None
