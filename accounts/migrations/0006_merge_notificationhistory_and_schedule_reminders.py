from django.db import migrations


class Migration(migrations.Migration):
    """Merge the two 0005 branches (通知履歴 / 予定のリマインダー設定)."""

    dependencies = [
        ("accounts", "0005_notificationhistory"),
        ("accounts", "0005_webpushsubscription_schedule_reminders_enabled"),
    ]

    operations = []
