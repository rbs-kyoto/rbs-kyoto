from datetime import timedelta

from django.conf import settings
from django.db import models


class Event(models.Model):
    class Recurrence(models.TextChoices):
        NONE = "none", "繰り返さない"
        DAILY = "daily", "毎日"
        WEEKLY = "weekly", "毎週"
        MONTHLY = "monthly", "毎月"

    title = models.CharField("タイトル", max_length=200)
    start = models.DateTimeField("開始")
    end = models.DateTimeField("終了", null=True, blank=True)
    all_day = models.BooleanField("終日", default=False)
    location = models.CharField("場所", max_length=200, blank=True)
    description = models.TextField("メモ", blank=True)
    recurrence = models.CharField(
        "繰り返し",
        max_length=10,
        choices=Recurrence.choices,
        default=Recurrence.NONE,
    )
    recurrence_until = models.DateField("繰り返しの終了日", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="作成者",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ["start"]
        verbose_name = "予定"
        verbose_name_plural = "予定"

    def __str__(self):
        return self.title

    @property
    def duration(self):
        if self.end and self.end > self.start:
            return self.end - self.start
        return timedelta(0)
