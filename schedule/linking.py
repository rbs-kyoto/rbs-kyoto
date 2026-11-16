"""機材アプリの貸出登録画面から、予定の機材と貸出記録を結ぶ。"""

from datetime import date

from .models import EventEquipment, UsageLink
from .recurrence import expand


def parse_link_params(data):
    """リクエストの schedule_item / schedule_date を検証して (item, day) を返す。不正なら None。"""
    raw_item = data.get("schedule_item", "")
    if not str(raw_item).isdigit():
        return None
    try:
        day = date.fromisoformat(data.get("schedule_date", ""))
    except ValueError:
        return None
    item = EventEquipment.objects.select_related("event", "equipment").filter(pk=raw_item).first()
    if item is None or not expand([item.event], day, day):
        return None
    return item, day


def link_usage(user, loan, data):
    """貸出 loan のうち、予定の機材に当たる明細を、その回に結ぶ。

    staff のみ、機材が一致する明細がある場合のみ。
    """
    if not user.is_staff:
        return None
    parsed = parse_link_params(data)
    if parsed is None:
        return None
    item, day = parsed
    line = loan.lines.filter(equipment_id=item.equipment_id).first()
    if line is None:
        return None
    return UsageLink.objects.create(item=item, date=day, usage=line)
