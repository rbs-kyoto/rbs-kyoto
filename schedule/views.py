import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import EventForm
from .models import Event
from .recurrence import expand

staff_required = user_passes_test(lambda user: user.is_staff)

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def _month_param(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        date(year, month, 1)
    except (TypeError, ValueError):
        return today.year, today.month
    return year, month


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _occurrences_by_day(range_start, range_end):
    """期間内の予定を {日付: [出現, ...]} にまとめる(複数日の予定は各日に入る)。"""
    # 繰り返し予定は開始が期間より前でも出現しうるので、開始が期間終端以前のものを対象にする
    candidates = Event.objects.filter(start__date__lte=range_end)
    by_day = {}
    for occ in expand(candidates, range_start, range_end):
        day = max(occ.first_day, range_start)
        while day <= min(occ.last_day, range_end):
            by_day.setdefault(day, []).append(occ)
            day += timedelta(days=1)
    return by_day


@login_required
def calendar_month(request):
    year, month = _month_param(request)
    today = timezone.localdate()

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]

    by_day = _occurrences_by_day(grid_start, grid_end)

    rows = [
        [
            {
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "occurrences": by_day.get(day, []),
            }
            for day in week
        ]
        for week in weeks
    ]

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)

    return render(
        request,
        "schedule/calendar.html",
        {
            "year": year,
            "month": month,
            "weekdays": WEEKDAYS,
            "rows": rows,
            "week_date": today if (today.year, today.month) == (year, month) else date(year, month, 1),
            "prev": {"year": prev_year, "month": prev_month},
            "next": {"year": next_year, "month": next_month},
        },
    )


def _date_param(request):
    try:
        return date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return timezone.localdate()


@login_required
def calendar_week(request):
    """指定した日を含む週(月曜始まり)を、日ごとに縦に並べて表示する。"""
    today = timezone.localdate()
    base = _date_param(request)
    week_start = base - timedelta(days=base.weekday())
    week_end = week_start + timedelta(days=6)

    by_day = _occurrences_by_day(week_start, week_end)
    days = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        days.append(
            {
                "date": day,
                "weekday": WEEKDAYS[i],
                "is_today": day == today,
                "is_sat": i == 5,
                "is_sun": i == 6,
                "occurrences": by_day.get(day, []),
            }
        )

    return render(
        request,
        "schedule/week.html",
        {
            "days": days,
            "week_start": week_start,
            "week_end": week_end,
            "prev_date": week_start - timedelta(days=7),
            "next_date": week_start + timedelta(days=7),
            "today": today,
        },
    )


@login_required
def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    return render(request, "schedule/event_detail.html", {"event": event})


@login_required
@staff_required
def event_create(request):
    initial = {}
    day = request.GET.get("date")
    if day:
        try:
            parsed = date.fromisoformat(day)
            initial["start"] = f"{parsed.isoformat()}T09:00"
        except ValueError:
            pass

    form = EventForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        event.save()
        return redirect("schedule:event_detail", pk=event.pk)

    return render(request, "schedule/event_form.html", {"form": form, "event": None})


@login_required
@staff_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("schedule:event_detail", pk=event.pk)

    return render(request, "schedule/event_form.html", {"form": form, "event": event})


@login_required
@staff_required
@require_POST
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    local = timezone.localtime(event.start)
    event.delete()
    return redirect(f"{reverse('schedule:calendar')}?year={local.year}&month={local.month}")
