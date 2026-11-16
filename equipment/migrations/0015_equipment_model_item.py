import django.db.models.deletion
from django.db import migrations, models


def split_into_models_and_items(apps, schema_editor):
    """Create one 機種 per distinct (分類, 名称, メーカー, 型番, 単位, 画像) and link items.

    Items that differ in any of these (including the photo) stay on separate
    機種 so no information is lost; they can be merged in the admin afterwards.
    """
    Equipment = apps.get_model("equipment", "Equipment")
    EquipmentModel = apps.get_model("equipment", "EquipmentModel")
    database = schema_editor.connection.alias
    models_by_key = {}
    for item in Equipment.objects.using(database).order_by("pk").iterator():
        key = (
            item.category_id,
            item.name,
            item.manufacturer_id,
            item.model_number,
            item.unit,
            item.image.name if item.image else "",
        )
        if key not in models_by_key:
            models_by_key[key] = EquipmentModel.objects.using(database).create(
                category_id=item.category_id,
                name=item.name,
                manufacturer_id=item.manufacturer_id,
                model_number=item.model_number,
                unit=item.unit,
                image=key[5],
            )
        Equipment.objects.using(database).filter(pk=item.pk).update(
            model=models_by_key[key]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0014_history_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="EquipmentModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="備品名")),
                ("model_number", models.CharField(blank=True, max_length=100, verbose_name="型番")),
                ("unit", models.CharField(default="個", max_length=20, verbose_name="単位")),
                ("image", models.ImageField(blank=True, upload_to="equipment/", verbose_name="画像")),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_models",
                        to="equipment.category",
                        verbose_name="分類",
                    ),
                ),
                (
                    "manufacturer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_models",
                        to="equipment.manufacturer",
                        verbose_name="メーカー",
                    ),
                ),
            ],
            options={
                "verbose_name": "機種",
                "verbose_name_plural": "機種",
                "ordering": ["name"],
            },
        ),
        migrations.AddIndex(
            model_name="equipmentmodel",
            index=models.Index(fields=["name"], name="equipment_e_name_352c02_idx"),
        ),
        migrations.AddField(
            model_name="equipment",
            name="model",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items",
                to="equipment.equipmentmodel",
                verbose_name="機種",
            ),
        ),
        migrations.RunPython(split_into_models_and_items, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="equipment", name="equipment_e_categor_221f6a_idx"),
        migrations.RemoveIndex(model_name="equipment", name="equipment_e_name_8baf3a_idx"),
        migrations.RemoveField(model_name="equipment", name="category"),
        migrations.RemoveField(model_name="equipment", name="name"),
        migrations.RemoveField(model_name="equipment", name="manufacturer"),
        migrations.RemoveField(model_name="equipment", name="model_number"),
        migrations.RemoveField(model_name="equipment", name="unit"),
        migrations.RemoveField(model_name="equipment", name="image"),
        migrations.AlterField(
            model_name="equipment",
            name="model",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items",
                to="equipment.equipmentmodel",
                verbose_name="機種",
            ),
        ),
        migrations.AddIndex(
            model_name="equipment",
            index=models.Index(fields=["model", "is_active"], name="equipment_e_model_i_e27ddf_idx"),
        ),
    ]
