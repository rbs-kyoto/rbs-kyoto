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
