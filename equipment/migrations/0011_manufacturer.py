import django.db.models.deletion
from django.db import migrations, models


def convert_manufacturer_text_to_master(apps, schema_editor):
    Manufacturer = apps.get_model("equipment", "Manufacturer")
    Equipment = apps.get_model("equipment", "Equipment")
    database = schema_editor.connection.alias
    manufacturers = {}
    for equipment in Equipment.objects.using(database).exclude(manufacturer_text="").iterator():
        name = " ".join(equipment.manufacturer_text.split())
        if not name:
            continue
        key = name.casefold()
        if key not in manufacturers:
            manufacturers[key] = Manufacturer.objects.using(database).get_or_create(
                name=name
            )[0]
        equipment.manufacturer_ref = manufacturers[key]
        equipment.save(using=database, update_fields=["manufacturer_ref"])


def restore_manufacturer_text(apps, schema_editor):
    Equipment = apps.get_model("equipment", "Equipment")
    database = schema_editor.connection.alias
    for equipment in Equipment.objects.using(database).exclude(
        manufacturer_ref=None
    ).select_related("manufacturer_ref"):
        equipment.manufacturer_text = equipment.manufacturer_ref.name
        equipment.save(using=database, update_fields=["manufacturer_text"])


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0010_equipmentreminderdelivery"),
    ]

    operations = [
        migrations.CreateModel(
            name="Manufacturer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="メーカー名")),
            ],
            options={
                "verbose_name": "メーカー",
                "verbose_name_plural": "メーカー",
                "ordering": ["name"],
            },
        ),
        migrations.RenameField(
            model_name="equipment",
            old_name="manufacturer",
            new_name="manufacturer_text",
        ),
        migrations.AddField(
            model_name="equipment",
            name="manufacturer_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="equipment",
                to="equipment.manufacturer",
                verbose_name="メーカー",
            ),
        ),
        migrations.RunPython(
            convert_manufacturer_text_to_master, restore_manufacturer_text
        ),
        migrations.RemoveField(model_name="equipment", name="manufacturer_text"),
        migrations.RenameField(
            model_name="equipment",
            old_name="manufacturer_ref",
            new_name="manufacturer",
        ),
    ]
