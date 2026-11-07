from django.db import migrations, models

LEGACY_FIELD_TO_KIND = {
    "登録": "register",
    "貸出・持出": "loan",
    "返却": "return",
    "備品の状態": "status",
}


def kind_for_legacy_entry(field_name, new_value):
    if field_name == "登録状態":
        return "unregister" if new_value == "登録解除" else "reactivate"
    return LEGACY_FIELD_TO_KIND.get(field_name, "update")


def assign_kinds(apps, schema_editor):
    EquipmentHistory = apps.get_model("equipment", "EquipmentHistory")
    database = schema_editor.connection.alias
    for entry in EquipmentHistory.objects.using(database).iterator():
        kind = kind_for_legacy_entry(entry.field_name, entry.new_value)
        if kind != entry.kind:
            EquipmentHistory.objects.using(database).filter(pk=entry.pk).update(kind=kind)


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0013_manager_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipmenthistory",
            name="kind",
            field=models.CharField(
                choices=[
                    ("register", "登録"),
                    ("update", "項目変更"),
                    ("loan", "貸出・持出"),
                    ("return", "返却"),
                    ("status", "状態変更"),
                    ("unregister", "登録解除"),
                    ("reactivate", "再有効化"),
                    ("import", "CSV取り込み"),
                ],
                default="update",
                max_length=12,
                verbose_name="種類",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmenthistory",
            index=models.Index(fields=["kind", "changed_at"], name="equipment_e_kind_eaae06_idx"),
        ),
        migrations.RunPython(assign_kinds, migrations.RunPython.noop),
    ]
