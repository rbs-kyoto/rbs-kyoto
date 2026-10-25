import json

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from opsd import maintenance, protocol


def superuser_only(view):
    @staff_member_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


def _spool():
    return settings.OPS_SPOOL


def maintenance_summary(spool):
    """画面に出す、メンテナンスの現在の状態。"""
    state = maintenance.read_state(spool) if spool else None
    if state is None:
        return {"known": False}
    applied = state.get("applied") or {}
    schedule = state.get("schedule", {})
    return {
        "known": True,
        "configured": state.get("configured", True),
        "active": bool(applied.get("enabled")),
        "message": applied.get("message", ""),
        "applied_at": (applied.get("at") or "")[:16].replace("T", " "),
        "error": state.get("last_error", ""),
        "mode": schedule.get("mode", "off"),
        "starts_at": (schedule.get("starts_at") or "")[:16].replace("T", " "),
        "auto_resume_at": (schedule.get("auto_resume_at") or "")[:16].replace("T", " "),
    }


@superuser_only
def index(request):
    spool = _spool()
    backups = protocol.list_backups(settings.OPS_BACKUPS) if settings.OPS_BACKUPS else []
    return render(
        request,
        "operations/index.html",
        {
            **admin.site.each_context(request),
            "title": "システムの操作",
            "enabled": spool is not None and spool.is_dir(),
            "actions": protocol.ACTIONS,
            "recent": protocol.list_recent(spool, 8) if spool and spool.is_dir() else [],
            "backups": backups[:10],
            "log_services": protocol.LOG_SERVICES,
            "restart_services": protocol.RESTARTABLE_SERVICES,
            "maintenance": maintenance_summary(spool if spool and spool.is_dir() else None),
        },
    )


@superuser_only
@require_POST
def run(request):
    spool = _spool()
    if spool is None or not spool.is_dir():
        return JsonResponse({"error": "この環境では操作ボタンを使えません。"}, status=503)
    try:
        body = json.loads(request.body or b"{}")
        action = body.get("action")
        params = body.get("params")
        # 復元は救出画面だけ。管理画面から誤って押せないようにする
        if action in ("restore", "rollback"):
            raise ValueError("復元は救出画面（/rescue/）から行ってください。")
        request_id = protocol.submit(spool, action, params, source=f"django:{request.user.get_username()}")
    except (ValueError, AttributeError) as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"id": request_id})


@superuser_only
def status(request, request_id):
    spool = _spool()
    result = protocol.read_status(spool, request_id) if spool is not None else None
    if result is None:
        raise Http404
    response = JsonResponse(result)
    response["Cache-Control"] = "no-store"
    return response
