"""StorageLocation を places.Place へ移す(状態のみ。DBは変更しない)。

Equipment.location の参照先と、StorageLocation モデルの定義を付け替える。
テーブルも列も同じものを使い続けるので、データには触れない。
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0010_equipmentreminderdelivery"),
        ("places", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="equipment",
                    name="location",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="equipment",
                        to="places.place",
                        verbose_name="保管場所",
                    ),
                ),
                migrations.RemoveConstraint(
                    model_name="storagelocation",
                    name="equipment_unique_sibling_location",
                ),
                migrations.DeleteModel(name="StorageLocation"),
            ],
        ),
    ]
