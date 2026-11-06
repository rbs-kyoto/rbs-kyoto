"""場所マスターの JSON API(読み取り専用。ログイン済みのセッションで利用する)。"""

from datetime import datetime, time, timedelta
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET

from .models import Place
from .services import find_conflicts, serialize_place, serialize_use

MAX_RANGE = timedelta(days=366)


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "ログインが必要です。"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _parse_moment(raw, *, end_of_day=False):
    """ISO 8601 の日時または日付を、タイムゾーンつきの日時にする。不正なら None。

    日付だけ(2026-11-14)の場合は、start なら0:00、end なら23:59:59 として、その日全体を表す。
    """
    if not raw:
        return None
    try:
        # 日付だけの文字列は、parse_datetime では「0:00の日時」と読まれてしまうので、先に調べる
        day = parse_date(raw)
        if day is not None:
            value = datetime.combine(day, time(23, 59, 59) if end_of_day else time(0, 0))
        else:
            value = parse_datetime(raw)
    except ValueError:
        return None
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return timezone.localtime(value)


@require_GET
@api_login_required
def place_list(request):
    kind = request.GET.get("kind", "all")
    if kind not in {"all", "venue", "storage"}:
        return JsonResponse({"error": "kind は all / venue / storage のいずれかです。"}, status=400)

    places = Place.objects.select_related("parent")
    if request.GET.get("include_inactive") != "1":
        places = places.filter(is_active=True)
    if kind == "venue":
        places = places.filter(is_venue=True)
    elif kind == "storage":
        places = places.filter(is_storage=True)
    query = request.GET.get("q", "").strip()
    if query:
        places = places.filter(name__icontains=query)
    return JsonResponse({"places": [serialize_place(place) for place in places]})


@require_GET
@api_login_required
def place_detail(request, pk):
    place = get_object_or_404(Place.objects.select_related("parent"), pk=pk)
    data = serialize_place(place)
    data["ancestors"] = [serialize_place(a) for a in reversed(place.ancestors())]
    data["children"] = [
        serialize_place(child)
        for child in place.children.select_related("parent").filter(is_active=True)
    ]
    data["description"] = place.description
    return JsonResponse(data)


@require_GET
@api_login_required
def place_usage(request, pk):
    place = get_object_or_404(Place.objects.select_related("parent"), pk=pk)
    start = _parse_moment(request.GET.get("start"))
    end = _parse_moment(request.GET.get("end"), end_of_day=True)
    if start is None or end is None:
        return JsonResponse(
            {"error": "start と end を ISO 8601 形式(例: 2026-11-14T09:00 または 2026-11-14)で指定してください。"},
            status=400,
        )
    if end < start:
        return JsonResponse({"error": "end は start 以降にしてください。"}, status=400)
    if end - start > MAX_RANGE:
        return JsonResponse({"error": "期間は最大366日までです。"}, status=400)

    # exclude=schedule:12 のように指定すると、編集中の予定自身などを除外できる(複数可)
    exclude = {}
    for raw in request.GET.getlist("exclude"):
        source, _, key = raw.partition(":")
        if source and key:
            exclude[source] = key

    conflicts = find_conflicts(place, start, end, exclude)
    return JsonResponse(
        {
            "place": serialize_place(place),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "available": not conflicts,
            "conflicts": [serialize_use(use) for use in conflicts],
        }
    )
