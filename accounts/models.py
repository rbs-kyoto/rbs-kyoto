from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import check_password, make_password

class User(AbstractUser):
    display_name = models.CharField(
        max_length = 100,
        blank = True
    )


class SuperuserGrantCredential(models.Model):
    password_hash = models.CharField("パスワードハッシュ", max_length=256, editable=False)

    class Meta:
        verbose_name = "スーパーユーザー昇格パスワード"
        verbose_name_plural = "スーパーユーザー昇格パスワード"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)


class WebPushSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=2048, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    equipment_reminders_enabled = models.BooleanField(
        "返却予定通知", default=True
    )
    news_notifications_enabled = models.BooleanField(
        "新着投稿通知", default=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Push通知購読"
        verbose_name_plural = "Push通知購読"

    def __str__(self):
        return f"{self.user} - Push通知"


class NotificationHistory(models.Model):
    class Kind(models.TextChoices):
        EQUIPMENT = "equipment", "返却予定"
        NEWS = "news", "新着投稿"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_history",
    )
    kind = models.CharField("種類", max_length=20, choices=Kind.choices)
    title = models.CharField("タイトル", max_length=200)
    body = models.CharField("本文", max_length=500, blank=True)
    url = models.CharField("リンク先", max_length=500, blank=True)
    sent_at = models.DateTimeField("送信日時", auto_now_add=True)

    class Meta:
        verbose_name = "通知履歴"
        verbose_name_plural = "通知履歴"
        ordering = ["-sent_at", "-pk"]
        indexes = [models.Index(fields=["user", "-sent_at"])]

    def __str__(self):
        return f"{self.user} - {self.title}"
