import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from .equipment_status import event_statuses, upcoming_problems
from .forms import (
    AssignmentFormSet,
    AttendanceForm,
    EventEquipmentFormSet,
    EventForm,
)
from .models import Attendance, Event
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


def _occurrence_date(event, raw):
    """詳細ページで扱う「何日の回か」を決める。繰り返し予定は、実在する回だけを受け付ける。"""
    try:
        wanted = date.fromisoformat(raw or "")
    except ValueError:
        wanted = None

    if wanted and expand([event], wanted, wanted):
        return wanted

    start_day = timezone.localtime(event.start).date()
    if event.recurrence == Event.Recurrence.NONE:
        return start_day
    today = timezone.localdate()
    upcoming = expand([event], today, today + timedelta(days=370))
    return upcoming[0].first_day if upcoming else start_day


def _my_assignment(user, event):
    """ログイン中のユーザーの割当(名簿とアカウントが連携していて、割り当てられている場合のみ)。"""
    entry = getattr(user, "roster_entry", None)
    if entry is None:
        return None
    return event.assignments.filter(member=entry).first()


def _lending_url(item, occurrence, day):
    """機材アプリの貸出登録画面を、この予定の内容入りで開くURL。"""
    params = {
        "equipment": item.equipment_id,
        "quantity": item.quantity,
        "started_at": occurrence.start.strftime("%Y-%m-%dT%H:%M"),
        "purpose": item.event.title,
        "schedule_item": item.pk,
        "schedule_date": day.isoformat(),
    }
    if item.event.end:
        params["due_at"] = occurrence.end.strftime("%Y-%m-%dT%H:%M")
    return f"{reverse('equipment:lending_register')}?{urlencode(params)}"


@login_required
def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    day = _occurrence_date(event, request.GET.get("date"))

    assignments = list(event.assignments.select_related("member"))
    responses = {
        a.assignment_id: a
        for a in Attendance.objects.filter(assignment__event=event, date=day)
    }
    rows = [
        {"assignment": a, "attendance": responses.get(a.pk)} for a in assignments
    ]

    mine = _my_assignment(request.user, event) if event.ask_attendance else None
    my_response = responses.get(mine.pk) if mine else None
    form = None
    if mine:
        form = AttendanceForm(
            initial={
                "status": my_response.status if my_response else None,
                "comment": my_response.comment if my_response else "",
            }
        )

    occurrence = next(
        (o for o in expand([event], day, day) if o.first_day == day), None
    ) or next(iter(expand([event], day, day)), None)
    equipment_rows = []
    for status in event_statuses(event, occurrence) if occurrence else []:
        equipment_rows.append(
            {
                "status": status,
                "lending_url": _lending_url(status.item, occurrence, day)
                if status.can_register_lending
                else None,
            }
        )
    # 表示中の回の問題は機材ごとのバッジで分かるので、それ以外の今後の回だけを警告にまとめる
    equipment_problems = [
        (problem_day, status)
        for problem_day, status in upcoming_problems(event, day)
        if problem_day != day
    ]

    summary = {label: 0 for _, label in Attendance.Status.choices}
    for row in rows:
        if row["attendance"]:
            summary[row["attendance"].get_status_display()] += 1
    summary["未回答"] = sum(1 for row in rows if not row["attendance"])

    return render(
        request,
        "schedule/event_detail.html",
        {
            "event": event,
            "day": day,
            "rows": rows,
            "summary": summary,
            "can_respond": mine is not None,
            "form": form,
            "equipment_rows": equipment_rows,
            "equipment_problems": equipment_problems,
        },
    )


@login_required
@require_POST
def event_respond(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not event.ask_attendance:
        raise Http404
    mine = _my_assignment(request.user, event)
    if mine is None:
        raise PermissionDenied

    try:
        day = date.fromisoformat(request.POST.get("date", ""))
    except ValueError:
        raise Http404
    if not expand([event], day, day):
        raise Http404

    form = AttendanceForm(request.POST)
    if form.is_valid():
        Attendance.objects.update_or_create(
            assignment=mine,
            date=day,
            defaults={
                "status": form.cleaned_data["status"],
                "comment": form.cleaned_data["comment"].strip(),
            },
        )
    return redirect(f"{reverse('schedule:event_detail', args=[event.pk])}?date={day.isoformat()}")


def _handle_event_form(request, event, initial=None):
    """予定と割当部員(フォームセット)をまとめて検証・保存する。保存できたら予定を返す。"""
    form = EventForm(request.POST or None, instance=event, initial=initial)
    formset = AssignmentFormSet(request.POST or None, instance=event)
    equipment_formset = EventEquipmentFormSet(request.POST or None, instance=event)
    if (
        request.method == "POST"
        and form.is_valid()
        and formset.is_valid()
        and equipment_formset.is_valid()
    ):
        with transaction.atomic():
            saved = form.save(commit=False)
            if saved.created_by_id is None:
                saved.created_by = request.user
            saved.save()
            formset.instance = saved
            formset.save()
            equipment_formset.instance = saved
            equipment_formset.save()
        return form, formset, equipment_formset, saved
    return form, formset, equipment_formset, None


@login_required
@staff_required
def event_create(request):
    initial = {}
    day = request.GET.get("date")
    if day:
        try:
            initial["start"] = f"{date.fromisoformat(day).isoformat()}T09:00"
        except ValueError:
            pass

    event = Event()
    form, formset, equipment_formset, saved = _handle_event_form(request, event, initial)
    if saved:
        return redirect("schedule:event_detail", pk=saved.pk)
    return render(
        request,
        "schedule/event_form.html",
        {
            "form": form,
            "formset": formset,
            "equipment_formset": equipment_formset,
            "event": None,
        },
    )


@login_required
@staff_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form, formset, equipment_formset, saved = _handle_event_form(request, event)
    if saved:
        return redirect("schedule:event_detail", pk=saved.pk)
    return render(
        request,
        "schedule/event_form.html",
        {
            "form": form,
            "formset": formset,
            "equipment_formset": equipment_formset,
            "event": event,
        },
    )


@login_required
@staff_required
@require_POST
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    local = timezone.localtime(event.start)
    event.delete()
    return redirect(f"{reverse('schedule:calendar')}?year={local.year}&month={local.month}")
