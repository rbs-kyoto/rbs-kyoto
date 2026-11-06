from django.db import migrations


def refuse_if_loans_are_missing(apps, schema_editor):
    """Safety net: never drop the legacy table before its rows were migrated."""
    UsageRecord = apps.get_model("equipment", "UsageRecord")
    Loan = apps.get_model("equipment", "Loan")
    db = schema_editor.connection.alias
    legacy_ids = set(UsageRecord.objects.using(db).values_list("pk", flat=True))
    migrated_ids = set(Loan.objects.using(db).values_list("pk", flat=True))
    missing = legacy_ids - migrated_ids
    if missing:
        raise RuntimeError(
            f"UsageRecord rows {sorted(missing)[:10]} have no matching Loan; "
            "refusing to drop the legacy table."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0016_loans_and_statuses"),
    ]

    operations = [
        migrations.RunPython(refuse_if_loans_are_missing, migrations.RunPython.noop),
        migrations.DeleteModel(name="UsageRecord"),
    ]
