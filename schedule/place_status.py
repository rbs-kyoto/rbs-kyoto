"""予定の場所について、他の予定と重なっていないかを調べる。"""

from datetime import timedelta

from places.services import find_conflicts

from .recurrence import expand


def place_conflicts(event, occ):
    """その回(occ)と時間が重なる、同じ(または上位・下位の)場所の利用。自分自身は除く。"""
    if event.place_id is None:
        return []
    return find_conflicts(event.place, occ.start, occ.end, exclude={"schedule": event.pk})


def upcoming_place_conflicts(event, from_day, limit=8):
    """from_day 以降の最大 limit 回について、競合のある回を [(日付, 利用のリスト)] で返す。"""
    if event.place_id is None:
        return []
    results = []
    for occ in expand([event], from_day, from_day + timedelta(days=120))[:limit]:
        conflicts = place_conflicts(event, occ)
        if conflicts:
            results.append((occ.first_day, conflicts))
    return results
