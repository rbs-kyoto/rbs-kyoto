"""予定を、場所マスター(places)の「利用状況」の提供者として登録する。"""

from django.utils import timezone

from places.registry import PlaceUse

from .models import Event
from .recurrence import expand


def provide(place_ids, start, end):
    """place_ids のいずれかを使う予定の回のうち、start〜end(両端を含む)と重なるもの。"""
    start = timezone.localtime(start)
    end = timezone.localtime(end)
    events = Event.objects.filter(
        place_id__in=place_ids, start__date__lte=end.date()
    ).select_related("place__parent")

    for occ in expand(events, start.date(), end.date()):
        if occ.start <= end and start <= occ.end:
            yield PlaceUse(
                source="schedule",
                key=occ.event.pk,
                title=occ.event.title,
                start=occ.start,
                end=occ.end,
                place=occ.event.place,
                url=f"/schedule/{occ.event.pk}/?date={occ.first_day.isoformat()}",
            )
