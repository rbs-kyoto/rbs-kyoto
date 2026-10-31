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


@login_required
def calendar_month(request):
    year, month = _month_param(request)
    today = timezone.localdate()

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]

    # 繰り返し予定は開始がグリッドより前でも出現しうるので、開始がグリッド終端以前のものを対象にする
    candidates = Event.objects.filter(start__date__lte=grid_end)
    occurrences = expand(candidates, grid_start, grid_end)

    by_day = {}
    for occ in occurrences:
        day = max(occ.first_day, grid_start)
        while day <= min(occ.last_day, grid_end):
            by_day.setdefault(day, []).append(occ)
            day += timedelta(days=1)

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
            "prev": {"year": prev_year, "month": prev_month},
            "next": {"year": next_year, "month": next_month},
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
