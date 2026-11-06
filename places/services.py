"""場所マスターの共通関数(アプリ間で使う Python の API)。"""

from .models import Place
from .registry import PROVIDERS, PlaceUse


def venues():
    """予定の場所として選べる場所。"""
    return Place.objects.filter(is_active=True, is_venue=True).select_related("parent")


def storage_places():
    """機材の保管場所として選べる場所。"""
    return Place.objects.filter(is_active=True, is_storage=True).select_related("parent")


def find_conflicts(place, start, end, exclude=None):
    """place を start〜end(両端を含む)に使っているものを、開始順に返す。

    親の場所を押さえていれば、その中の場所も使えないものとして扱う
    (自分・上位・下位の場所が対象)。
    exclude は {提供者名: 提供元の id} で、編集中の予定自身などを除くのに使う。
    """
    if place is None:
        return []
    ids = place.related_ids()
    exclude = exclude or {}
    uses = []
    for provider in PROVIDERS.values():
        for use in provider(ids, start, end):
            if use.source in exclude and str(exclude[use.source]) == str(use.key):
                continue
            uses.append(use)
    uses.sort(key=lambda use: (use.start, use.title))
    return uses


def is_available(place, start, end, exclude=None):
    return not find_conflicts(place, start, end, exclude)


def serialize_place(place):
    return {
        "id": place.pk,
        "name": place.name,
        "code": place.code,
        "path": str(place),
        "parent_id": place.parent_id,
        "is_active": place.is_active,
        "is_storage": place.is_storage,
        "is_venue": place.is_venue,
    }


def serialize_use(use: PlaceUse):
    return {
        "source": use.source,
        "title": use.title,
        "start": use.start.isoformat(),
        "end": use.end.isoformat(),
        "place_id": use.place.pk,
        "place_path": str(use.place),
        "url": use.url,
    }
