from .models import EquipmentHistory

Kind = EquipmentHistory.Kind


def record_event(
    equipment,
    kind,
    by,
    *,
    field_name="",
    old_value="",
    new_value="",
    reason="",
    loan_line=None,
):
    """Append one entry to the equipment's history.

    This is the only place that creates history rows: views, the admin and the
    CSV import all go through it.
    """
    if kind not in Kind.values:
        raise ValueError(f"Unknown event kind: {kind!r}")
    return EquipmentHistory.objects.create(
        equipment=equipment,
        kind=kind,
        changed_by=by,
        field_name=field_name or Kind(kind).label,
        old_value="" if old_value is None else str(old_value),
        new_value="" if new_value is None else str(new_value),
        reason=reason,
        loan_line=loan_line,
    )
