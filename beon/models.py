from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class BeonCategory(models.Model):
    name = models.CharField("カテゴリ名", max_length=100)
    description = models.TextField("説明", blank=True)
    event_date = models.DateField("開催日", null=True, blank=True)
    venue = models.CharField("会場", max_length=200, blank=True)
    latitude = models.DecimalField("緯度", max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField("経度", max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField("有効", default=True)
    order = models.PositiveIntegerField("表示順", default=0)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        ordering = ("order", "event_date", "id")
        verbose_name = "BeONカテゴリ"
        verbose_name_plural = "BeONカテゴリ"

    def __str__(self):
        return self.name


class BeonSession(models.Model):
    class Status(models.TextChoices):
        PREPARING = "preparing", "準備中"
        READY = "ready", "待機"
        RUNNING = "running", "運用中"
        FINISHED = "finished", "終了"

    category = models.ForeignKey(
        BeonCategory, on_delete=models.CASCADE,
        related_name="sessions", verbose_name="カテゴリ",
    )
    name = models.CharField("セッション名", max_length=100)
    description = models.TextField("説明", blank=True)
    starts_at = models.DateTimeField("開始予定", null=True, blank=True)
    ends_at = models.DateTimeField("終了予定", null=True, blank=True)
    status = models.CharField(
        "状態", max_length=12, choices=Status.choices,
        default=Status.PREPARING,
    )
    order = models.PositiveIntegerField("表示順", default=0)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        ordering = ("order", "starts_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("category", "name"),
                name="beon_unique_session_name_per_category",
            ),
        ]
        verbose_name = "BeONセッション"
        verbose_name_plural = "BeONセッション"

    def __str__(self):
        return f"{self.category.name}｜{self.name}"

    @property
    def is_joinable(self):
        return self.status in (self.Status.READY, self.Status.RUNNING)


class BeonSessionMember(models.Model):
    class Role(models.TextChoices):
        CHIEF = "chief", "チーフ"
        DIRECTOR = "director", "ディレクター"
        ANNOUNCER = "announcer", "アナウンサー"

    session = models.ForeignKey(
        BeonSession, on_delete=models.CASCADE,
        related_name="assignments", verbose_name="セッション",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="beon_assignments", verbose_name="ユーザー",
    )
    role = models.CharField("担当", max_length=12, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("session", "role"),
                name="beon_one_user_per_role",
            ),
            models.UniqueConstraint(
                fields=("session", "user"),
                name="beon_one_role_per_user_in_session",
            ),
        ]
        ordering = ("role",)
        verbose_name = "BeON担当割当"
        verbose_name_plural = "BeON担当割当"

    def __str__(self):
        return f"{self.session}｜{self.get_role_display()}｜{self.user}"


class BeonPresence(models.Model):
    """ユーザーが現在入室しているセッション。ユーザーごとに1行のみ。"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="beon_presence", verbose_name="ユーザー",
    )
    session = models.ForeignKey(
        BeonSession, on_delete=models.CASCADE,
        related_name="presences", verbose_name="入室中セッション",
    )
    entered_at = models.DateTimeField("入室日時", default=timezone.now)
    last_seen = models.DateTimeField("最終応答日時", default=timezone.now)

    class Meta:
        verbose_name = "BeON入室状態"
        verbose_name_plural = "BeON入室状態"

    def __str__(self):
        return f"{self.user}｜{self.session}"

    @classmethod
    def release_stale(cls, minutes=2):
        threshold = timezone.now() - timedelta(minutes=minutes)
        return cls.objects.filter(last_seen__lt=threshold).delete()
