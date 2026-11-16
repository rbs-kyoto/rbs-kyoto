import django.db.models.deletion
from django.db import migrations, models


def convert_manager_to_position(apps, schema_editor):
    """Move the managing person to a managing position.

    A person with exactly one position maps to that position. People with none
    or several positions are left blank for manual setup. The original person's
    name is kept in the notes so no information is lost.
    """
    Equipment = apps.get_model("equipment", "Equipment")
    database = schema_editor.connection.alias
    queryset = (
        Equipment.objects.using(database)
        .exclude(manager_person=None)
        .select_related("manager_person")
    )
    for equipment in queryset:
        person = equipment.manager_person
        positions = list(person.positions.all()[:2])
        if len(positions) == 1:
            equipment.manager_position = positions[0]
        note = f"【旧管理担当者】{person.name}"
        equipment.notes = f"{equipment.notes}\n{note}".strip()
        equipment.save(using=database, update_fields=["manager_position", "notes"])


def restore_manager_person(apps, schema_editor):
    # The original person cannot be recovered reliably from a position.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("roll", "0003_add_attendance_number"),
        ("equipment", "0012_renumber_inventory_numbers"),
    ]

    operations = [
        migrations.RenameField(
            model_name="equipment",
            old_name="manager",
            new_name="manager_person",
        ),
        migrations.AlterField(
            model_name="equipment",
            name="manager_person",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="roll.rosterentry",
            ),
        ),
        migrations.AddField(
            model_name="equipment",
            name="manager_position",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="managed_equipment",
                to="roll.position",
                verbose_name="管理担当役職",
            ),
        ),
        migrations.RunPython(convert_manager_to_position, restore_manager_person),
        migrations.RemoveField(model_name="equipment", name="manager_person"),
        migrations.RenameField(
            model_name="equipment",
            old_name="manager_position",
            new_name="manager",
        ),
    ]
