"""予定(Event)を繰り返しルールに従って期間内の「出現(occurrence)」へ展開する。"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone

from .models import Event

# 無限ループ防止の上限
MAX_OCCURRENCES = 2000


@dataclass(frozen=True)
class Occurrence:
    event: Event
    start: datetime  # ローカル時刻
    end: datetime  # ローカル時刻(終日は終了日の 23:59 扱い)

    @property
    def first_day(self) -> date:
        return self.start.date()

    @property
    def last_day(self) -> date:
        return self.end.date()


def _add_months(dt: datetime, months: int):
    """同じ日付のまま月を進める。その月に存在しない日(31日など)は None。"""
    index = dt.month - 1 + months
    year, month = dt.year + index // 12, index % 12 + 1
    if dt.day > calendar.monthrange(year, month)[1]:
        return None
    return dt.replace(year=year, month=month)


def _starts(event: Event, local_start: datetime, until: date):
    """繰り返しルールに沿った開始日時を until(含む)まで順に返す。"""
    kind = event.recurrence
    if kind == Event.Recurrence.NONE:
        yield local_start
        return

    step = 0
    while step < MAX_OCCURRENCES:
        if kind == Event.Recurrence.DAILY:
            current = local_start + timedelta(days=step)
        elif kind == Event.Recurrence.WEEKLY:
            current = local_start + timedelta(weeks=step)
        else:
            current = _add_months(local_start, step)
            if current is None:
                step += 1
                continue
        if current.date() > until:
            return
        yield current
        step += 1


def expand(events, range_start: date, range_end: date):
    """range_start〜range_end(両端含む)に1日でもかかる出現を開始順で返す。"""
    result = []
    for event in events:
        local_start = timezone.localtime(event.start)
        duration = event.duration
        limit = range_end
        if event.recurrence != Event.Recurrence.NONE and event.recurrence_until:
            limit = min(limit, event.recurrence_until)

        for start in _starts(event, local_start, limit):
            if event.all_day:
                # 終日予定は日付だけを使い、終了日の終わりまでを範囲とする
                last_day = (start + duration).date()
                end = start.replace(
                    year=last_day.year,
                    month=last_day.month,
                    day=last_day.day,
                    hour=23,
                    minute=59,
                )
            else:
                end = start + duration
            if end.date() < range_start or start.date() > range_end:
                continue
            result.append(Occurrence(event=event, start=start, end=end))

    result.sort(key=lambda o: (o.start, o.event.title))
    return result
