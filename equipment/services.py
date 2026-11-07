"""Operations that change an item's status or move it in and out.

Views, the admin and imports go through these so every rule (which statuses
may follow which, how much can be lent, what a bad return does) lives here.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .events import Kind, record_event
from .models import Equipment, Loan, LoanLine, ReturnRecord

Status = Equipment.Condition

# 保存する状態の遷移。登録解除は別操作(未返却の貸出がないこと)で行う。
STATUS_TRANSITIONS = {
    Status.NORMAL: {Status.INSPECTION, Status.BROKEN, Status.DISABLED, Status.LOST},
    Status.INSPECTION: {Status.NORMAL, Status.REPAIR, Status.BROKEN},
    Status.REPAIR: {Status.NORMAL, Status.BROKEN},
    Status.BROKEN: {Status.REPAIR},
    Status.DISABLED: {Status.NORMAL},
    Status.LOST: {Status.NORMAL},
}


class LoanError(Exception):
    """A lending/return request that cannot be carried out."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def allowed_next_statuses(current):
    return STATUS_TRANSITIONS.get(current, set())


def can_change_status(current, new):
    return current == new or new in allowed_next_statuses(current)


def change_status(equipment, to, by, reason="", *, force=False):
    """Move an item to another status and record it. Returns True if it changed.

    ``force`` skips the transition table; use it when a physical fact decides
    (e.g. the item came back broken).
    """
    old = equipment.condition
    if old == to:
        return False
    if not force and not can_change_status(old, to):
        raise ValidationError(
            f"「{Status(old).label}」から「{Status(to).label}」には変更できません。"
        )
    equipment.condition = to
    equipment.last_modified_by = by
    equipment.save()
    record_event(
        equipment,
        Kind.STATUS,
        by,
        field_name="備品の状態",
        old_value=Status(old).label,
        new_value=Status(to).label,
        reason=reason,
    )
    return True


def split_item(equipment, quantity, to, by, reason=""):
    """Split ``quantity`` units off a counted lot into a new item with status ``to``."""
    if not 0 < quantity < equipment.quantity:
        raise ValueError("分割する数量は1以上、保有数量未満にしてください。")
    new_item = Equipment(
        model=equipment.model,
        receipt_number=equipment.receipt_number,
        quantity=quantity,
        manager=equipment.manager,
        location=equipment.location,
        purchased_on=equipment.purchased_on,
        purchase_price=equipment.purchase_price,
        purchase_currency=equipment.purchase_currency,
        purchase_vendor=equipment.purchase_vendor,
        warranty_expiry=equipment.warranty_expiry,
        expected_lifespan_years=equipment.expected_lifespan_years,
        notes=equipment.notes,
        condition=to,
        created_by=by,
        last_modified_by=by,
    )
    new_item.save()
    old_quantity = equipment.quantity
    equipment.quantity = old_quantity - quantity
    equipment.last_modified_by = by
    equipment.save()
    record_event(
        equipment,
        Kind.UPDATE,
        by,
        field_name="保有数量",
        old_value=old_quantity,
        new_value=equipment.quantity,
        reason=f"{Status(to).label}の{quantity}{equipment.unit}を{new_item.inventory_number}に分割。{reason}".strip(),
    )
    record_event(
        new_item,
        Kind.REGISTER,
        by,
        new_value=f"{new_item.inventory_number} {new_item.name}",
        reason=f"{equipment.inventory_number}から{quantity}{equipment.unit}を分割（{Status(to).label}）。{reason}".strip(),
    )
    return new_item


@transaction.atomic
def create_loan(user, items, **loan_fields):
    """Create a loan for ``items`` = [(equipment_id, quantity), ...] atomically."""
    if not items:
        raise LoanError("equipment", "貸し出す備品を選択してください。")
    ids = [equipment_id for equipment_id, _ in items]
    if len(set(ids)) != len(ids):
        raise LoanError("equipment", "同じ備品が重複しています。")
    locked = {
        equipment.pk: equipment
        for equipment in Equipment.objects.select_for_update()
        .filter(pk__in=ids, is_active=True)
        .order_by("pk")
        .select_related("model")
    }
    for equipment_id, quantity in items:
        equipment = locked.get(equipment_id)
        if equipment is None:
            raise LoanError("equipment", "貸出できない備品が含まれています。")
        if equipment.condition not in Equipment.LOANABLE_CONDITIONS:
            raise LoanError(
                "equipment",
                f"{equipment.inventory_number}は「{equipment.get_condition_display()}」のため貸出できません。",
            )
        if quantity > equipment.available_quantity:
            raise LoanError(
                "quantity",
                f"貸出可能数量を超えています（{equipment.inventory_number}は現在 "
                f"{equipment.available_quantity}{equipment.unit}）。",
            )
    loan = Loan.objects.create(created_by=user, **loan_fields)
    for equipment_id, quantity in items:
        equipment = locked[equipment_id]
        line = LoanLine.objects.create(
            loan=loan, equipment=equipment, quantity=quantity
        )
        record_event(
            equipment,
            Kind.LOAN,
            user,
            new_value=(
                f"{loan.get_usage_type_display()} {loan.destination} "
                f"{quantity}{equipment.unit}"
            ),
            loan_line=line,
        )
    return loan


# 返却時の状態 → 個体の状態
RETURN_CONDITION_TO_STATUS = {
    ReturnRecord.Condition.INSPECTION: Status.INSPECTION,
    ReturnRecord.Condition.FAULTY: Status.BROKEN,
    ReturnRecord.Condition.DAMAGED: Status.BROKEN,
    ReturnRecord.Condition.MISSING: Status.LOST,
}


@transaction.atomic
def record_return(line_id, user, record):
    """Save a ReturnRecord (unsaved ``record``) for a line and apply its effect.

    A return that is not "問題なし" moves the returned units to the matching
    status: the whole item if every unit is affected, otherwise those units
    are split off into their own item.
    """
    equipment_id = LoanLine.objects.values_list("equipment_id", flat=True).get(
        pk=line_id
    )
    equipment = (
        Equipment.objects.select_for_update().select_related("model").get(pk=equipment_id)
    )
    line = LoanLine.objects.select_related("loan").get(pk=line_id)
    remaining = line.remaining_quantity
    if record.quantity > remaining:
        raise LoanError(
            "quantity",
            f"返却可能数量を超えています（残り {remaining}{equipment.unit}）。",
        )
    record.line = line
    record.processed_by = user
    record.save()
    record_event(
        equipment,
        Kind.RETURN,
        user,
        new_value=f"{record.quantity}{equipment.unit} {record.get_condition_display()}",
        reason=record.condition_details,
        loan_line=line,
    )
    target = RETURN_CONDITION_TO_STATUS.get(record.condition)
    if target is not None and equipment.condition != target:
        if record.quantity >= equipment.quantity:
            change_status(
                equipment, target, user, record.condition_details, force=True
            )
        else:
            split_item(
                equipment, record.quantity, target, user, record.condition_details
            )
    return record
