import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import staff_required

from .forms import RosterImportForm
from .importer import RosterImportError, import_roster_csv
from .models import RosterEntry


@login_required
@staff_required
def roster_list(request):
    entries = RosterEntry.objects.select_related("account").prefetch_related("positions")
    entry_type = request.GET.get("type", "").strip()
    query = request.GET.get("q", "").strip()
    if entry_type in RosterEntry.EntryType.values:
        entries = entries.filter(entry_type=entry_type)
    if request.GET.get("members") == "1":
        entries = entries.filter(is_member=True)
    if query:
        entries = entries.filter(
            Q(name__icontains=query)
            | Q(name_kana__icontains=query)
            | Q(school_identifier__icontains=query)
            | Q(grade__icontains=query)
            | Q(homeroom__icontains=query)
            | Q(account__username__icontains=query)
            | Q(account__email__icontains=query)
        )
    return render(
        request,
        "roll/roster_list.html",
        {
            "entries": entries,
            "entry_types": RosterEntry.EntryType.choices,
            "selected_type": entry_type,
            "query": query,
            "show_members": request.GET.get("members") == "1",
            "admin_url": reverse("admin:roll_rosterentry_changelist"),
            "import_url": reverse("roll:import_csv"),
        },
    )


@login_required
@staff_required
def import_csv(request):
    result = None
    error = None
    if request.method == "POST":
        form = RosterImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                created_count, updated_count = import_roster_csv(
                    form.cleaned_data["csv_file"]
                )
            except (RosterImportError, csv.Error) as import_error:
                error = str(import_error)
            else:
                result = (
                    f"インポートしました（新規 {created_count} 件、更新 {updated_count} 件）。"
                )
                form = RosterImportForm()
    else:
        form = RosterImportForm()
    return render(
        request,
        "roll/import_csv.html",
        {
            "form": form,
            "error": error,
            "result": result,
            "list_url": reverse("roll:list"),
        },
    )
