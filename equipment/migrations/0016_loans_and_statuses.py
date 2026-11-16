import secrets
import string

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

BAD_RETURN_TO_STATUS = {"damaged": "broken", "faulty": "broken", "missing": "lost"}


def _next_inventory_number(queryset, category_code, day):
    fiscal_year = day.year if day.month >= 4 else day.year - 1
    prefix = f"{category_code}-{fiscal_year % 100:02d}"
    last = 0
    for number in queryset.filter(inventory_number__startswith=prefix).values_list(
        "inventory_number", flat=True
    ):
        tail = number[len(prefix):]
        if len(tail) == 6 and tail.isdigit():
            last = max(last, int(tail))
    return f"{prefix}{last + 1:06d}"


def _new_qr_token(queryset):
    alphabet = string.ascii_letters + string.digits
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(12))
        if not queryset.filter(qr_token=token).exists():
            return token


def migrate_loans_and_unavailable_units(apps, schema_editor):
    db = schema_editor.connection.alias
    UsageRecord = apps.get_model("equipment", "UsageRecord")
    Loan = apps.get_model("equipment", "Loan")
    LoanLine = apps.get_model("equipment", "LoanLine")
    ReturnRecord = apps.get_model("equipment", "ReturnRecord")
    Reminder = apps.get_model("equipment", "EquipmentReminderDelivery")
    Equipment = apps.get_model("equipment", "Equipment")
    History = apps.get_model("equipment", "EquipmentHistory")

    # 1. UsageRecord -> Loan + LoanLine, keeping the same ids so old URLs still work.
    for usage in UsageRecord.objects.using(db).order_by("pk"):
        Loan.objects.using(db).create(
            id=usage.pk,
            usage_type=usage.usage_type,
            destination=usage.destination,
            destination_entry_id=usage.destination_entry_id,
            responsible_person_id=usage.responsible_person_id,
            recipient=usage.recipient,
            started_at=usage.started_at,
            due_at=usage.due_at,
            purpose=usage.purpose,
            notes=usage.notes,
            created_by_id=usage.created_by_id,
        )
        Loan.objects.using(db).filter(pk=usage.pk).update(created_at=usage.created_at)
        LoanLine.objects.using(db).create(
            id=usage.pk,
            loan_id=usage.pk,
            equipment_id=usage.equipment_id,
            quantity=usage.quantity,
        )
    for record in ReturnRecord.objects.using(db).all():
        ReturnRecord.objects.using(db).filter(pk=record.pk).update(line_id=record.usage_id)
    for delivery in Reminder.objects.using(db).all():
        Reminder.objects.using(db).filter(pk=delivery.pk).update(line_id=delivery.usage_id)

    # 2. Units that came back damaged/faulty/missing used to be subtracted from
    #    the stock forever. Give them their own item with a proper status.
    today = timezone.localdate()
    for equipment in Equipment.objects.using(db).select_related("model__category").order_by("pk"):
        totals = {"broken": 0, "lost": 0}
        for record in ReturnRecord.objects.using(db).filter(line__equipment_id=equipment.pk):
            status = BAD_RETURN_TO_STATUS.get(record.condition)
            if status:
                totals[status] += record.quantity
        remaining = equipment.quantity
        allocated = []
        for status, quantity in totals.items():
            take = min(quantity, remaining)
            if take > 0:
                allocated.append((status, take))
                remaining -= take
        if not allocated:
            continue

        old_quantity = equipment.quantity
        if remaining == 0:
            # Every unit is affected: the item itself takes the first status.
            status, take = allocated[0]
            if equipment.condition != "repair":
                equipment.condition = status
            equipment.quantity = take
            split = allocated[1:]
        else:
            equipment.quantity = remaining
            split = allocated
        equipment.save(using=db)
        if equipment.quantity != old_quantity:
            History.objects.using(db).create(
                equipment=equipment,
                kind="update",
                field_name="保有数量",
                old_value=str(old_quantity),
                new_value=str(equipment.quantity),
                reason="返却時の故障・紛失分を別の備品番号に分割（移行）",
            )
        for status, take in split:
            number = _next_inventory_number(
                Equipment.objects.using(db), equipment.model.category.code, today
            )
            new_item = Equipment.objects.using(db).create(
                model_id=equipment.model_id,
                inventory_number=number,
                qr_inventory_number=number,
                qr_token=_new_qr_token(Equipment.objects.using(db)),
                receipt_number=equipment.receipt_number,
                quantity=take,
                manager_id=equipment.manager_id,
                location_id=equipment.location_id,
                purchased_on=equipment.purchased_on,
                purchase_price=equipment.purchase_price,
                purchase_currency=equipment.purchase_currency,
                purchase_vendor=equipment.purchase_vendor,
                warranty_expiry=equipment.warranty_expiry,
                expected_lifespan_years=equipment.expected_lifespan_years,
                notes=equipment.notes,
                condition=status,
            )
            History.objects.using(db).create(
                equipment=new_item,
                kind="register",
                field_name="登録",
                new_value=f"{number} {equipment.model.name}",
                reason=f"{equipment.inventory_number}から返却時の故障・紛失分を分割（移行）",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("roll", "0003_add_attendance_number"),
        ("accounts", "0003_webpushsubscription"),
        ("equipment", "0015_equipment_model_item"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Loan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("usage_type", models.CharField(choices=[("lending", "貸出中"), ("carry_out", "持出中")], max_length=12, verbose_name="区分")),
                ("destination", models.CharField(help_text="貸出時点の表示名のスナップショット。名簿の変更後も記録として残す。", max_length=200, verbose_name="貸出・持出先")),
                ("recipient", models.CharField(blank=True, max_length=100, verbose_name="受取担当者")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="開始日時")),
                ("due_at", models.DateTimeField(blank=True, null=True, verbose_name="返却予定日時")),
                ("purpose", models.CharField(blank=True, max_length=250, verbose_name="用途")),
                ("notes", models.TextField(blank=True, verbose_name="備考")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="登録日時")),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_equipment_loans", to=settings.AUTH_USER_MODEL, verbose_name="登録者")),
                ("destination_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="equipment_loans", to="roll.rosterentry", verbose_name="名簿上の貸出・持出先")),
                ("responsible_person", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="responsible_loans", to="roll.rosterentry", verbose_name="責任者")),
            ],
            options={"verbose_name": "貸出・持出", "verbose_name_plural": "貸出・持出", "ordering": ["-started_at", "-pk"]},
        ),
        migrations.CreateModel(
            name="LoanLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name="数量")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="loan_lines", to="equipment.equipment")),
                ("loan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="equipment.loan")),
            ],
            options={"verbose_name": "貸出明細", "verbose_name_plural": "貸出明細", "ordering": ["-loan__started_at", "-loan_id", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="loanline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gte", 1)), name="equipment_loanline_quantity_at_least_one"),
        ),
        migrations.AddField(
            model_name="returnrecord",
            name="line",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="returns", to="equipment.loanline"),
        ),
        migrations.AddField(
            model_name="equipmentreminderdelivery",
            name="line",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="reminder_deliveries", to="equipment.loanline"),
        ),
        migrations.AddField(
            model_name="equipmenthistory",
            name="loan_line",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="equipment.loanline", verbose_name="貸出明細"),
        ),
        migrations.AlterField(
            model_name="equipment",
            name="condition",
            field=models.CharField(
                choices=[("normal", "正常"), ("inspection", "要点検"), ("repair", "修理中"), ("broken", "故障"), ("disabled", "使用停止"), ("lost", "紛失")],
                default="normal",
                max_length=12,
                verbose_name="備品の状態",
            ),
        ),
        migrations.AlterField(
            model_name="returnrecord",
            name="condition",
            field=models.CharField(
                choices=[("normal", "問題なし"), ("inspection", "要点検"), ("faulty", "故障"), ("missing", "紛失"), ("damaged", "破損")],
                default="normal",
                max_length=10,
                verbose_name="返却時の状態",
            ),
        ),
        migrations.AlterField(
            model_name="returnrecord",
            name="condition_details",
            field=models.TextField(blank=True, verbose_name="故障・紛失の内容"),
        ),
        migrations.RunPython(migrate_loans_and_unavailable_units, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="equipmentreminderdelivery", name="equipment_unique_reminder_delivery"),
        migrations.RemoveField(model_name="equipmentreminderdelivery", name="usage"),
        migrations.AlterField(
            model_name="equipmentreminderdelivery",
            name="line",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reminder_deliveries", to="equipment.loanline"),
        ),
        migrations.AddConstraint(
            model_name="equipmentreminderdelivery",
            constraint=models.UniqueConstraint(fields=("subscription", "line", "due_at_snapshot", "days_until_due"), name="equipment_unique_reminder_delivery"),
        ),
        migrations.RemoveField(model_name="returnrecord", name="usage"),
        migrations.AlterField(
            model_name="returnrecord",
            name="line",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="returns", to="equipment.loanline"),
        ),
    ]
