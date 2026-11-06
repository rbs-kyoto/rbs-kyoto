"""equipment.StorageLocation を places.Place として引き継ぐ(状態のみ。DBは変更しない)。

テーブル equipment_storagelocation と主キーをそのまま使うので、データは動かさない。
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("equipment", "0010_equipmentreminderdelivery"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Place",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("name", models.CharField(max_length=100, verbose_name="場所名")),
                        ("code", models.CharField(blank=True, max_length=30, verbose_name="場所コード")),
                        ("description", models.TextField(blank=True, verbose_name="詳細")),
                        ("notes", models.TextField(blank=True, verbose_name="備考")),
                        ("is_active", models.BooleanField(default=True, verbose_name="使用中")),
                        (
                            "parent",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="children",
                                to="places.place",
                                verbose_name="上位の場所",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "場所",
                        "verbose_name_plural": "場所",
                        "db_table": "equipment_storagelocation",
                        "ordering": ["name"],
                    },
                ),
                migrations.AddConstraint(
                    model_name="place",
                    constraint=models.UniqueConstraint(
                        fields=("parent", "name"), name="equipment_unique_sibling_location"
                    ),
                ),
            ],
        ),
    ]
