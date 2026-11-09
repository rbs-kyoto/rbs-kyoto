import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from .equipment_status import event_statuses, upcoming_problems
from .place_status import place_conflicts, upcoming_place_conflicts
from roll.models import Position, RosterEntry

from .forms import (
    AssignmentSelection,
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
    candidates = Event.objects.filter(start__date__lte=range_end).select_related(
        "place__parent"
    )
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
    place_warnings = place_conflicts(event, occurrence) if occurrence else []
    place_upcoming = [
        (problem_day, conflicts)
        for problem_day, conflicts in upcoming_place_conflicts(event, day)
        if problem_day != day
    ]
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
            "place_warnings": place_warnings,
            "place_upcoming": place_upcoming,
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


def _roster_context(event, post=None):
    """割当部員を選ぶ名簿の表に出す行と、フィルターの選択肢。

    post があれば(入力エラーで再表示するとき)、その選択と役割を保つ。
    すでに割り当てた人は、部員でなくなっていても表に残す。
    """
    assigned = {}
    if event.pk:
        assigned = {
            a.member_id: a
            for a in event.assignments.annotate(response_count=Count("attendances"))
        }
    entries = list(
        RosterEntry.objects.filter(Q(is_member=True) | Q(pk__in=assigned)).prefetch_related(
            "positions"
        )
    )

    checked_ids = set()
    if post is not None:
        checked_ids = {int(v) for v in post.getlist("assign_member") if str(v).isdigit()}

    rows = []
    for entry in entries:
        if post is not None:
            checked = entry.pk in checked_ids
            role = post.get(f"role_{entry.pk}", "")
        else:
            current = assigned.get(entry.pk)
            checked = current is not None
            role = current.role if current else ""
        positions = list(entry.positions.all())
        class_label = " ".join(
            part
            for part in (
                f"{entry.grade}年" if entry.grade else "",
                f"{entry.homeroom}組" if entry.homeroom else "",
            )
            if part
        )
        rows.append(
            {
                "entry": entry,
                "checked": checked,
                "role": role,
                "class_label": class_label,
                "positions": positions,
                "position_ids": "," + ",".join(str(p.pk) for p in positions) + ",",
                "response_count": assigned[entry.pk].response_count if entry.pk in assigned else 0,
                "is_former_member": not entry.is_member,
            }
        )

    position_ids = {p.pk for row in rows for p in row["positions"]}
    return {
        "rows": rows,
        "grades": sorted({row["entry"].grade for row in rows if row["entry"].grade}),
        "homerooms": sorted({row["entry"].homeroom for row in rows if row["entry"].homeroom}),
        "positions": Position.objects.filter(pk__in=position_ids),
        "types": [
            (value, label)
            for value, label in RosterEntry.EntryType.choices
            if any(row["entry"].entry_type == value for row in rows)
        ],
        "checked_count": sum(1 for row in rows if row["checked"]),
    }


COPY_SOURCE_LIMIT = 40


def _copy_sources(event):
    """割当のコピー元にできる予定(割当のあるもの)を、開始が新しい順に返す。

    フォームの JS が、選ばれた予定の割当(名簿の id と役割)を、表に反映するのに使う。
    """
    events = (
        Event.objects.filter(assignments__isnull=False)
        .exclude(pk=event.pk)
        .distinct()
        .order_by("-start", "-pk")
        .prefetch_related("assignments")[:COPY_SOURCE_LIMIT]
    )
    sources = []
    for source in events:
        assignments = list(source.assignments.all())
        local = timezone.localtime(source.start)
        sources.append(
            {
                "id": source.pk,
                "label": f"{local.month}/{local.day} {source.title}（{len(assignments)}人）",
                "roles": {str(a.member_id): a.role for a in assignments},
            }
        )
    return sources


def _handle_event_form(request, event, initial=None):
    """予定・割当部員・使う機材をまとめて検証・保存する。保存できたら予定を返す。"""
    posting = request.method == "POST"
    form = EventForm(request.POST or None, instance=event, initial=initial)
    selection = AssignmentSelection(request.POST, event) if posting else None
    equipment_formset = EventEquipmentFormSet(request.POST or None, instance=event)
    if (
        posting
        and form.is_valid()
        and selection.is_valid()
        and equipment_formset.is_valid()
    ):
        with transaction.atomic():
            saved = form.save(commit=False)
            if saved.created_by_id is None:
                saved.created_by = request.user
            saved.save()
            selection.save(saved)
            equipment_formset.instance = saved
            equipment_formset.save()
        return form, selection, equipment_formset, saved
    return form, selection, equipment_formset, None


def _form_context(request, event, form, selection, equipment_formset, page_event):
    return {
        "form": form,
        "equipment_formset": equipment_formset,
        "event": page_event,
        "roster": _roster_context(event, request.POST if selection is not None else None),
        "copy_sources": _copy_sources(event),
        "roster_errors": selection.errors if selection is not None else [],
    }


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
    form, selection, equipment_formset, saved = _handle_event_form(request, event, initial)
    if saved:
        return redirect("schedule:event_detail", pk=saved.pk)
    return render(
        request,
        "schedule/event_form.html",
        _form_context(request, event, form, selection, equipment_formset, None),
    )


@login_required
@staff_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form, selection, equipment_formset, saved = _handle_event_form(request, event)
    if saved:
        return redirect("schedule:event_detail", pk=saved.pk)
    return render(
        request,
        "schedule/event_form.html",
        _form_context(request, event, form, selection, equipment_formset, event),
    )


@login_required
@staff_required
@require_POST
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    local = timezone.localtime(event.start)
    event.delete()
    return redirect(f"{reverse('schedule:calendar')}?year={local.year}&month={local.month}")
