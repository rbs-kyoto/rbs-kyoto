from django.db import migrations
from django.utils import timezone


def fiscal_year_code(day):
    fiscal_year = day.year if day.month >= 4 else day.year - 1
    return f"{fiscal_year % 100:02d}"


def renumber_inventory_numbers(apps, schema_editor):
    """Reassign every number as <category><fiscal yy><6-digit serial> by registration order.

    qr_inventory_number is intentionally left untouched so that printed QR codes
    keep working.
    """
    Equipment = apps.get_model("equipment", "Equipment")
    database = schema_editor.connection.alias
    counters = {}
    assignments = []
    queryset = (
        Equipment.objects.using(database)
        .select_related("category")
        .order_by("created_at", "pk")
    )
    for equipment in queryset:
        registered_on = timezone.localtime(equipment.created_at).date()
        prefix = f"{equipment.category.code}-{fiscal_year_code(registered_on)}"
        counters[prefix] = counters.get(prefix, 0) + 1
        assignments.append((equipment.pk, f"{prefix}{counters[prefix]:06d}"))

    # Move to temporary values first so a unique clash can never occur mid-way.
    for pk, _ in assignments:
        Equipment.objects.using(database).filter(pk=pk).update(
            inventory_number=f"TMP-{pk}"
        )
    for pk, number in assignments:
        Equipment.objects.using(database).filter(pk=pk).update(
            inventory_number=number
        )


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0011_merge_manufacturer_and_places"),
    ]

    operations = [
        migrations.RunPython(renumber_inventory_numbers, migrations.RunPython.noop),
    ]
