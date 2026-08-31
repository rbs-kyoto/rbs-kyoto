from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from accounts.decorators import staff_required
from .models import Event, Program, Role, Assignment

User = get_user_model()


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
                next_order = (event.programs.count())
                Program.objects.create(event=event, name=name, order=next_order)
        elif "add_assignment" in request.POST:
            program = get_object_or_404(Program, pk=request.POST.get("program"), event=event)
            role = get_object_or_404(Role, pk=request.POST.get("role"))
            member = get_object_or_404(User, pk=request.POST.get("member"))
            Assignment.objects.create(program=program, role=role, member=member)

        return redirect("shifts:event_assign", pk=event.pk)

    programs = event.programs.prefetch_related("assignments__role", "assignments__member")
    roles = Role.objects.all()
    members = User.objects.order_by("username")

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
                        member = get_object_or_404(User, pk=member_id)
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
    members = User.objects.order_by("username")

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
def my_assignments(request):
    assignments = (
        Assignment.objects.filter(member=request.user)
        .select_related("role", "program", "program__event")
        .order_by("program__event__date", "program__order")
    )

    return render(
        request,
        "shifts/my_assignments.html",
        {"assignments": assignments},
    )
