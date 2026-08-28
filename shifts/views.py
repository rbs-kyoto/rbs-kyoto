from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from .models import Event, Assignment


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
