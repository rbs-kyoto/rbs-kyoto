from django.conf import settings
from django.db import models
from django.utils import timezone


class ProofreadRole(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="添削ユーザー",
        on_delete=models.CASCADE,
        related_name="revise_proofread_role",
    )
    granted_at = models.DateTimeField("付与日時", auto_now_add=True)

    class Meta:
        verbose_name = "添削ロール"
        verbose_name_plural = "添削ロール"

    def __str__(self):
        return f"{self.user}（添削）"


class RevisePost(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="投稿者",
        on_delete=models.CASCADE,
        related_name="revise_posts",
    )
    title = models.CharField("タイトル", max_length=200)
    body = models.TextField("原稿")
    instruction = models.TextField("どう直したいか", blank=True)
    target_seconds = models.PositiveIntegerField("目標尺（秒）", null=True, blank=True)
    is_practice = models.BooleanField("練習用", default=False)
    status = models.CharField(
        "状態",
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
    )
    closed_at = models.DateTimeField("Close日時", null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Closeした人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField("投稿日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Revise投稿"
        verbose_name_plural = "Revise投稿"

    def __str__(self):
        return f"{self.title}（{self.get_status_display()}）"


class ReviseComment(models.Model):
    post = models.ForeignKey(
        RevisePost,
        verbose_name="投稿",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="投稿者",
        on_delete=models.CASCADE,
        related_name="revise_comments",
    )
    body = models.TextField("コメント")
    created_at = models.DateTimeField("投稿日時", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Reviseコメント"
        verbose_name_plural = "Reviseコメント"


class ManualRevision(models.Model):
    post = models.ForeignKey(
        RevisePost,
        verbose_name="投稿",
        on_delete=models.CASCADE,
        related_name="manual_revisions",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="添削者",
        on_delete=models.CASCADE,
        related_name="revise_manual_revisions",
    )
    revised_body = models.TextField("添正文")
    observations = models.JSONField("6観点とその他", default=dict)
    audio = models.FileField(
        "音声お手本",
        upload_to="revise/audio/",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("投稿日時", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "手動添削"
        verbose_name_plural = "手動添削"


class LearningPair(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "承認待ち"
        APPROVED = "approved", "承認済み"
        REJECTED = "rejected", "却下"

    post = models.ForeignKey(
        RevisePost,
        verbose_name="投稿",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="learning_pairs",
    )
    before_text = models.TextField("修正前")
    after_text = models.TextField("修正後")
    rule_codes = models.CharField("ルール番号", max_length=200, blank=True)
    status = models.CharField(
        "承認状態",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="承認者",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField("承認日時", null=True, blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "学習ペア"
        verbose_name_plural = "学習ペア"
