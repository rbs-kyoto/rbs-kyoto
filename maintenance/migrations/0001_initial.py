from django.db import migrations, models


def create_maintenance_setting(apps, schema_editor):
    maintenance_setting = apps.get_model("maintenance", "MaintenanceSetting")
    maintenance_setting.objects.using(schema_editor.connection.alias).get_or_create(
        pk=1
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MaintenanceSetting",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("off", "通常運用"),
                            ("planned", "計画メンテナンス"),
                            ("emergency", "緊急メンテナンス"),
                        ],
                        default="off",
                        max_length=16,
                        verbose_name="運用状態",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="計画メンテナンスの自動開始日時です。",
                        null=True,
                        verbose_name="開始予定日時",
                    ),
                ),
                (
                    "resume_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="利用者への告知専用です。この日時を過ぎても自動再開しません。",
                        null=True,
                        verbose_name="再開予定日時",
                    ),
                ),
                (
                    "auto_resume_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="計画メンテナンスの自動再開日時です。空欄の場合は手動で解除してください。",
                        null=True,
                        verbose_name="自動再開日時",
                    ),
                ),
                (
                    "recovery_in_progress",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "自動再開日時を過ぎてもメンテナンスを継続する場合は、"
                            "自動再開日時までに有効にしてください。"
                        ),
                        verbose_name="予定時刻後も復旧作業を継続",
                    ),
                ),
                (
                    "announcement",
                    models.TextField(
                        blank=True,
                        help_text="任意。メンテナンス画面に表示します。",
                        verbose_name="告知内容",
                    ),
                ),
            ],
            options={
                "verbose_name": "メンテナンス設定",
                "verbose_name_plural": "メンテナンス設定",
            },
        ),
        migrations.RunPython(
            create_maintenance_setting,
            migrations.RunPython.noop,
        ),
    ]
