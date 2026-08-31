import csv
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from accounts.decorators import staff_required
from .models import Event, Program, Role, Member, Assignment

User = get_user_model()

# Excelで保存したCSVはShift-JIS(cp932)になりがちなので、UTF-8を試してから
# フォールバックする。
CSV_ENCODINGS = ("utf-8-sig", "cp932")

# ヘッダーの表記ゆれを吸収するための別名。
NAME_HEADER_ALIASES = {"氏名", "name", "名前"}
USERNAME_HEADER_ALIASES = {"ユーザー名", "username", "アカウント"}


def _decode_csv(uploaded_file):
    raw = uploaded_file.read()
    for encoding in CSV_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _parse_roster_rows(text):
    """(name, username_or_None) のリストを返す。

    ヘッダー行の有無・列名の表記ゆれ・ヘッダー無し(1列目=氏名)のどちらにも対応する。
    """
    reader = list(csv.reader(io.StringIO(text)))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return []

    header = [cell.strip() for cell in rows[0]]
    name_col = next((i for i, h in enumerate(header) if h in NAME_HEADER_ALIASES), None)

    if name_col is not None:
        username_col = next(
            (i for i, h in enumerate(header) if h in USERNAME_HEADER_ALIASES), None
        )
        data_rows = rows[1:]
    else:
        # ヘッダー行が無い＝1列目がそのまま氏名。
        name_col, username_col = 0, None
        data_rows = rows

    parsed = []
    for row in data_rows:
        if name_col >= len(row):
            continue
        name = row[name_col].strip()
        if not name:
            continue
        username = None
        if username_col is not None and username_col < len(row):
            username = row[username_col].strip() or None
        parsed.append((name, username))

    return parsed


@login_required
def event_list(request):
    events = Event.objects.all()
    if not request.user.is_staff:
        events = events.filter(is_active=True)

    return render(request, "shifts/event_list.html", {"events": events})


@login_required
@staff_required
def event_create(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        date = request.POST.get("date", "").strip()
        is_active = bool(request.POST.get("is_active"))

        if title and date:
            event = Event.objects.create(title=title, date=date, is_active=is_active)
            return redirect("shifts:event_assign", pk=event.pk)

        return render(
            request,
            "shifts/event_form.html",
            {"error": "イベント名と日付を入力してください。", "title": title, "date": date, "is_active": is_active},
        )

    return render(request, "shifts/event_form.html", {"is_active": True})


@login_required
def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not event.is_active and not request.user.is_staff:
        raise Http404

    programs = event.programs.prefetch_related("assignments__role", "assignments__member")

    return render(
        request,
        "shifts/event_detail.html",
        {"event": event, "programs": programs},
    )


@login_required
def event_detail_grid(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not event.is_active and not request.user.is_staff:
        raise Http404

    programs = list(event.programs.all())
    roles = list(Role.objects.all())
    assignments = Assignment.objects.filter(program__event=event).select_related("role", "program", "member")
    lookup = {(a.program_id, a.role_id): a for a in assignments}

    grid_rows = [
        {"program": program, "cells": [lookup.get((program.pk, role.pk)) for role in roles]}
        for program in programs
    ]

    return render(
        request,
        "shifts/event_detail_grid.html",
        {"event": event, "roles": roles, "grid_rows": grid_rows},
    )


@login_required
@staff_required
def event_assign(request, pk):
    event = get_object_or_404(Event, pk=pk)

    if request.method == "POST":
        if "add_program" in request.POST:
            name = request.POST.get("name", "").strip()
            if name:
                next_order = event.programs.count()
                Program.objects.create(event=event, name=name, order=next_order)
        elif "add_member" in request.POST:
            name = request.POST.get("member_name", "").strip()
            if name:
                Member.objects.create(name=name)
        elif "add_assignment" in request.POST:
            program = get_object_or_404(Program, pk=request.POST.get("program"), event=event)
            role = get_object_or_404(Role, pk=request.POST.get("role"))
            member = get_object_or_404(Member, pk=request.POST.get("member"))
            Assignment.objects.create(program=program, role=role, member=member)

        return redirect("shifts:event_assign", pk=event.pk)

    programs = event.programs.prefetch_related("assignments__role", "assignments__member")
    roles = Role.objects.all()
    members = Member.objects.order_by("name")

    return render(
        request,
        "shifts/event_assign.html",
        {"event": event, "programs": programs, "roles": roles, "members": members},
    )


@login_required
@staff_required
def event_assign_grid(request, pk):
    event = get_object_or_404(Event, pk=pk)
    programs = list(event.programs.all())
    roles = list(Role.objects.all())

    if request.method == "POST":
        # グリッドは「1種目×1役割につき1人」という前提でしか編集できない。
        # 同じ組み合わせに複数人いる場合はここでは触らず、リスト編集に任せる。
        for program in programs:
            for role in roles:
                existing_qs = Assignment.objects.filter(program=program, role=role)
                if existing_qs.count() > 1:
                    continue

                member_id = request.POST.get(f"cell_{program.pk}_{role.pk}", "")
                existing = existing_qs.first()

                if member_id:
                    if existing is None:
                        member = get_object_or_404(Member, pk=member_id)
                        Assignment.objects.create(program=program, role=role, member=member)
                    elif str(existing.member_id) != member_id:
                        existing.member_id = member_id
                        existing.save(update_fields=["member"])
                elif existing is not None:
                    existing.delete()

        return redirect("shifts:event_assign_grid", pk=event.pk)

    assignments = Assignment.objects.filter(program__event=event).select_related("role", "program", "member")
    lookup = {}
    multi_cells = set()
    for a in assignments:
        key = (a.program_id, a.role_id)
        if key in lookup:
            multi_cells.add(key)
        else:
            lookup[key] = a

    grid_rows = [
        {
            "program": program,
            "cells": [
                {
                    "role": role,
                    "assignment": lookup.get((program.pk, role.pk)),
                    "is_multi": (program.pk, role.pk) in multi_cells,
                }
                for role in roles
            ],
        }
        for program in programs
    ]
    members = Member.objects.order_by("name")

    return render(
        request,
        "shifts/event_assign_grid.html",
        {"event": event, "roles": roles, "grid_rows": grid_rows, "members": members},
    )


@login_required
@staff_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    event_pk = assignment.program.event_id

    if request.method == "POST":
        assignment.delete()

    return redirect("shifts:event_assign", pk=event_pk)


@login_required
@staff_required
def program_delete(request, pk):
    program = get_object_or_404(Program, pk=pk)
    event_pk = program.event_id

    if request.method == "POST":
        program.delete()

    return redirect("shifts:event_assign", pk=event_pk)


@login_required
@staff_required
def roster(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            Member.objects.create(name=name)
        return redirect("shifts:roster")

    members = Member.objects.select_related("user").order_by("name")
    return render(request, "shifts/roster.html", {"members": members})


@login_required
@staff_required
def roster_import(request):
    result = None

    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            result = {"error": "CSVファイルを選択してください。"}
        else:
            text = _decode_csv(csv_file)
            if text is None:
                result = {"error": "文字コードを判別できませんでした。UTF-8またはShift-JISで保存し直してください。"}
            else:
                rows = _parse_roster_rows(text)
                if not rows:
                    result = {"error": "読み込める行がありませんでした。1列目に氏名を入れてください。"}
                else:
                    created = linked = skipped = 0
                    for name, username in rows:
                        member, was_created = Member.objects.get_or_create(name=name)
                        created += int(was_created)
                        skipped += int(not was_created)

                        if username and not member.user_id:
                            user = User.objects.filter(username=username).first()
                            if user and not Member.objects.filter(user=user).exclude(pk=member.pk).exists():
                                member.user = user
                                member.save(update_fields=["user"])
                                linked += 1

                    result = {"created": created, "skipped": skipped, "linked": linked, "total": len(rows)}

    return render(request, "shifts/roster_import.html", {"result": result})


@login_required
def my_assignments(request):
    assignments = (
        Assignment.objects.filter(member__user=request.user)
        .select_related("role", "program", "program__event", "member")
        .order_by("program__event__date", "program__order")
    )

    return render(
        request,
        "shifts/my_assignments.html",
        {"assignments": assignments},
    )
