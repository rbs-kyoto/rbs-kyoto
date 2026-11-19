from django.conf import settings
from django.db import models
from django.utils import timezone


class Script(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="作成者",
        on_delete=models.CASCADE,
        related_name="gucchi_scripts",
    )
    title = models.CharField("タイトル", max_length=200, blank=True)
    source_text = models.TextField("原稿")
    target_seconds = models.PositiveIntegerField("目標尺（秒）", null=True, blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "ぐっちくん原稿"
        verbose_name_plural = "ぐっちくん原稿"

    def __str__(self):
        return self.title or f"{self.owner}の原稿"


class ScriptRevision(models.Model):
    class Kind(models.TextChoices):
        ORIGINAL = "original", "初稿"
        KEEP_LENGTH = "keep_length", "尺キープ"
        SHORTEN = "shorten", "短縮"

    script = models.ForeignKey(
        Script,
        verbose_name="原稿",
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    kind = models.CharField("種類", max_length=20, choices=Kind.choices)
    text = models.TextField("本文")
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "原稿改訂"
        verbose_name_plural = "原稿改訂"


class GucchiJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "待機中"
        RUNNING = "running", "実行中"
        SUCCEEDED = "succeeded", "完了"
        FAILED = "failed", "失敗"
        CANCELLED = "cancelled", "キャンセル"

    class Kind(models.TextChoices):
        DETERMINISTIC_CHECK = "deterministic_check", "決定論チェック"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="依頼者",
        on_delete=models.CASCADE,
        related_name="gucchi_jobs",
    )
    script = models.ForeignKey(
        Script,
        verbose_name="原稿",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    kind = models.CharField("種類", max_length=32, choices=Kind.choices)
    status = models.CharField(
        "状態",
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    payload = models.JSONField("入力", default=dict)
    result = models.JSONField("結果", null=True, blank=True)
    error = models.TextField("エラー", blank=True)
    memory_limit_mb = models.PositiveIntegerField("メモリ上限（MB）", null=True, blank=True)
    queued_at = models.DateTimeField("待機開始日時", default=timezone.now)
    started_at = models.DateTimeField("開始日時", null=True, blank=True)
    finished_at = models.DateTimeField("終了日時", null=True, blank=True)

    class Meta:
        ordering = ["queued_at", "pk"]
        verbose_name = "ぐっちくんジョブ"
        verbose_name_plural = "ぐっちくんジョブ"
        indexes = [
            models.Index(fields=["status", "queued_at"]),
            models.Index(fields=["owner", "-queued_at"]),
        ]

    @property
    def queue_position(self):
        if self.status != self.Status.QUEUED:
            return 0
        return GucchiJob.objects.filter(
            status=self.Status.QUEUED,
            queued_at__lte=self.queued_at,
        ).count()
