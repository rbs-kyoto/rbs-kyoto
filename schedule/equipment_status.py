"""予定で使う機材について、その回に「予約できているか」を判定する。

機材アプリの貸出・持出記録は、開始日時に関係なく記録があれば在庫を減らす。
そのため予約は予定側の「使う機材と数量」として持ち、当日に貸出登録した記録を
UsageLink で結んで「貸出中」「返却済み」に切り替える。
"""

from dataclasses import dataclass, field
from datetime import timedelta

from equipment.models import Equipment, UsageRecord

from .models import EventEquipment
from .recurrence import expand

OK = "ok"
LENT = "lent"
RETURNED = "returned"
CONFLICT = "conflict"
SHORT = "short"
UNAVAILABLE = "unavailable"

# 警告として目立たせる状態
PROBLEMS = {CONFLICT, SHORT, UNAVAILABLE}
# まだ貸出登録していない(登録ボタンを出す)状態
NOT_YET_LENT = {OK, CONFLICT, SHORT}

UNUSABLE_CONDITIONS = {
    Equipment.Condition.REPAIR,
    Equipment.Condition.BROKEN,
    Equipment.Condition.DISABLED,
}


@dataclass
class ItemStatus:
    item: EventEquipment
    code: str
    label: str
    reasons: list = field(default_factory=list)

    @property
    def is_problem(self):
        return self.code in PROBLEMS

    @property
    def can_register_lending(self):
        return self.code in NOT_YET_LENT


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def _linked_usages(item, day):
    return [link.usage for link in item.usage_links.all() if link.date == day]


def _remaining(usages):
    return sum(usage.remaining_quantity for usage in usages)


def _other_event_demand(item, occ):
    """同じ機材を、重なる時間帯に押さえている他の予定。 [(名前, 数量)]"""
    demands = []
    others = (
        EventEquipment.objects.filter(equipment=item.equipment)
        .exclude(event=item.event)
        .select_related("event")
        .prefetch_related("usage_links__usage__returns")
    )
    for other in others:
        for other_occ in expand([other.event], occ.first_day, occ.last_day):
            if not _overlaps(occ.start, occ.end, other_occ.start, other_occ.end):
                continue
            linked = _linked_usages(other, other_occ.first_day)
            quantity = _remaining(linked) if linked else other.quantity
            if quantity:
                demands.append((other.event.title, quantity))
            break
    return demands


def _outside_usage_demand(item, occ):
    """予定とは無関係に、いま貸出・持出中で、返却予定がこの時間帯と重なるもの。"""
    demands = []
    usages = UsageRecord.objects.filter(
        equipment=item.equipment, schedule_link__isnull=True
    ).prefetch_related("returns")
    for usage in usages:
        remaining = usage.remaining_quantity
        if not remaining:
            continue
        if usage.started_at > occ.end:
            continue
        if usage.due_at and usage.due_at < occ.start:
            continue
        demands.append((usage.destination, remaining))
    return demands


def item_status(item, occ):
    """予定の機材1件について、その回(occ)の状態を返す。"""
    equipment = item.equipment

    linked = _linked_usages(item, occ.first_day)
    if linked:
        if _remaining(linked):
            return ItemStatus(item, LENT, linked[0].get_usage_type_display())
        return ItemStatus(item, RETURNED, "返却済み")

    if not equipment.is_active or equipment.condition in UNUSABLE_CONDITIONS:
        return ItemStatus(
            item,
            UNAVAILABLE,
            "利用不可",
            ["修理中・故障・使用停止中、または登録解除されています。"],
        )

    if item.quantity > equipment.quantity:
        return ItemStatus(
            item,
            SHORT,
            "数量不足",
            [
                f"保有 {equipment.quantity}{equipment.unit} に対して "
                f"{item.quantity}{equipment.unit} 必要です。"
            ],
        )

    reasons = []
    total = item.quantity
    for title, quantity in _other_event_demand(item, occ):
        total += quantity
        reasons.append(f"予定「{title}」が {quantity}{equipment.unit} 使用予定です。")
    for destination, quantity in _outside_usage_demand(item, occ):
        total += quantity
        reasons.append(
            f"「{destination}」へ {quantity}{equipment.unit} 貸出・持出中です。"
        )

    if total > equipment.quantity:
        return ItemStatus(item, CONFLICT, "競合", reasons)
    return ItemStatus(item, OK, "予約OK")


def event_statuses(event, occ):
    items = event.equipment_items.select_related("equipment").prefetch_related(
        "usage_links__usage__returns"
    )
    return [item_status(item, occ) for item in items]


def upcoming_problems(event, from_day, limit=8):
    """from_day 以降の最大 limit 回について、問題のある機材を [(日付, ItemStatus)] で返す。"""
    if not event.equipment_items.exists():
        return []
    problems = []
    occurrences = expand([event], from_day, from_day + timedelta(days=120))[:limit]
    for occ in occurrences:
        for status in event_statuses(event, occ):
            if status.is_problem:
                problems.append((occ.first_day, status))
    return problems
