import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """UsageLink の紐付け先を、旧 UsageRecord から LoanLine に付け替える。

    equipment の移行(0016)で、LoanLine の主キーは旧 UsageRecord の主キーと同じ値で
    作られているため、既存の紐付けはそのまま新しい参照先に対応する。
    """

    dependencies = [
        ("schedule", "0005_event_place"),
        ("equipment", "0016_loans_and_statuses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usagelink",
            name="usage",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="schedule_link",
                to="equipment.loanline",
                verbose_name="貸出・持出記録(明細)",
            ),
        ),
    ]
