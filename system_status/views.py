from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from unfold.widgets import UnfoldAdminTextareaWidget

from .checks import refresh, refresh_if_stale
from .models import Level, SystemStatus

_BADGES = {
    Level.OK: "success",
    Level.WARNING: "warning",
    Level.DANGER: "danger",
    Level.INFO: "neutral",
    Level.UNKNOWN: "neutral",
}


class NotesForm(forms.ModelForm):
    class Meta:
        model = SystemStatus
        fields = ["notes"]
        widgets = {"notes": UnfoldAdminTextareaWidget}


@staff_member_required
def status(request):
    current = refresh_if_stale()
    items = [
        {**item, "level_label": Level(item["level"]).label, "badge": _BADGES[Level(item["level"])]}
        for item in current.results
    ]
    if current.count(Level.DANGER):
        summary = ("danger", "すぐに対応が必要な項目があります。")
    elif current.count(Level.WARNING):
        summary = ("warning", "近いうちに対応が必要な項目があります。")
    else:
        summary = ("success", "問題はありません。")

    return render(
        request,
        "system_status/status.html",
        {
            **admin.site.each_context(request),
            "title": "システムの状態",
            "status": current,
            "items": items,
            "summary": summary,
            "notes_form": NotesForm(instance=current) if request.user.is_superuser else None,
        },
    )


@staff_member_required
@require_POST
def check_now(request):
    refresh()
    messages.success(request, "確認しました。")
    return redirect("system_status:status")


@staff_member_required
@require_POST
def update_notes(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = NotesForm(request.POST, instance=SystemStatus.get_solo())
    if form.is_valid():
        form.save()
        messages.success(request, "メモを保存しました。")
    return redirect("system_status:status")
