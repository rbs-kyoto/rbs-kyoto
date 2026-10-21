from django.core.exceptions import ValidationError
from django.db import models


class MaintenanceSetting(models.Model):
    class Mode(models.TextChoices):
        OFF = "off", "通常運用"
        PLANNED = "planned", "計画メンテナンス"
        EMERGENCY = "emergency", "緊急メンテナンス"

    class Status(models.TextChoices):
        INACTIVE = "inactive", "通常運用"
        ACTIVE = "active", "メンテナンス中"
        RECOVERY = "recovery", "復旧作業中"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    mode = models.CharField(
        "運用状態",
        max_length=16,
        choices=Mode.choices,
        default=Mode.OFF,
    )
    starts_at = models.DateTimeField(
        "開始予定日時",
        null=True,
        blank=True,
        help_text="計画メンテナンスの自動開始日時です。",
    )
    resume_at = models.DateTimeField(
        "再開予定日時",
        null=True,
        blank=True,
        help_text="利用者への告知専用です。この日時を過ぎても自動再開しません。",
    )
    auto_resume_at = models.DateTimeField(
        "自動再開日時",
        null=True,
        blank=True,
        help_text="計画メンテナンスの自動再開日時です。空欄の場合は手動で解除してください。",
    )
    recovery_in_progress = models.BooleanField(
        "予定時刻後も復旧作業を継続",
        default=False,
        help_text=(
            "自動再開日時を過ぎてもメンテナンスを継続する場合は、"
            "自動再開日時までに有効にしてください。"
        ),
    )
    announcement = models.TextField(
        "告知内容",
        blank=True,
        help_text="任意。メンテナンス画面に表示します。",
    )

    class Meta:
        verbose_name = "メンテナンス設定"
        verbose_name_plural = "メンテナンス設定"

    def __str__(self):
        return "メンテナンス設定"

    @classmethod
    def get_solo(cls):
        setting, _ = cls.objects.get_or_create(pk=1)
        return setting

    def clean(self):
        super().clean()
        if self.mode == self.Mode.PLANNED and not self.starts_at:
            raise ValidationError({"starts_at": "計画メンテナンスの開始日時を指定してください。"})
        if (
            self.mode == self.Mode.PLANNED
            and self.starts_at
            and self.auto_resume_at
            and self.auto_resume_at <= self.starts_at
        ):
            raise ValidationError(
                {"auto_resume_at": "自動再開日時は開始予定日時より後にしてください。"}
            )

    def status_at(self, now):
        if self.mode == self.Mode.OFF:
            return self.Status.INACTIVE
        if self.mode == self.Mode.EMERGENCY:
            return self.Status.RECOVERY if self.recovery_in_progress else self.Status.ACTIVE
        if not self.starts_at or now < self.starts_at:
            return self.Status.INACTIVE
        if self.auto_resume_at and now >= self.auto_resume_at:
            return (
                self.Status.RECOVERY
                if self.recovery_in_progress
                else self.Status.INACTIVE
            )
        return self.Status.ACTIVE
