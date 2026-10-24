from django.db import models


class Level(models.TextChoices):
    OK = "ok", "問題なし"
    INFO = "info", "情報"
    UNKNOWN = "unknown", "確認できず"
    WARNING = "warning", "注意"
    DANGER = "danger", "要対応"


class SystemStatus(models.Model):
    """最後に確認した結果と、引き継ぎ用のメモ（1行だけ）。"""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    results = models.JSONField("確認結果", default=list, blank=True)
    checked_at = models.DateTimeField("最終確認日時", null=True, blank=True)
    notes = models.TextField(
        "困ったときの連絡先・引き継ぎメモ",
        blank=True,
        help_text="OB・OGや顧問の先生の連絡先、ドメインの登録先など、次の担当者に伝えたいことを書いてください。",
    )

    class Meta:
        verbose_name = "システムの状態"
        verbose_name_plural = "システムの状態"

    def __str__(self):
        return "システムの状態"

    @classmethod
    def get_solo(cls):
        status, _ = cls.objects.get_or_create(pk=1)
        return status

    def count(self, *levels):
        return sum(1 for result in self.results if result.get("level") in levels)
