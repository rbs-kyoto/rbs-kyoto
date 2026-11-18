from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError, transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import SessionAssignmentForm
from .models import (
    BeonCategory, BeonPresence, BeonSession, BeonSessionMember,
)


def _display_name(user):
    return user.get_full_name() or user.get_username()


@login_required
def category_list(request):
    categories = BeonCategory.objects.filter(is_active=True).prefetch_related("sessions")
    assigned_ids = BeonSessionMember.objects.filter(
        user=request.user
    ).values_list("session__category_id", flat=True)
    categories = categories.filter(pk__in=assigned_ids).distinct()
    return render(request, "beon/category_list.html", {"categories": categories})


@login_required
def session_list(request, category_id):
    category = get_object_or_404(BeonCategory, pk=category_id, is_active=True)
    sessions = (
        BeonSession.objects.filter(
            category=category,
            assignments__user=request.user,
        )
        .distinct()
        .prefetch_related("assignments")
    )
    return render(
        request, "beon/session_list.html",
        {"category": category, "sessions": sessions},
    )


@login_required
def join_session(request, session_id):
    if request.method != "POST":
        return redirect("beon:categories")

    session = get_object_or_404(
        BeonSession.objects.select_related("category"), pk=session_id
    )

    if not BeonSessionMember.objects.filter(
        session=session, user=request.user
    ).exists():
        return HttpResponseForbidden("このセッションへの参加権限がありません。")

    if not session.is_joinable:
        messages.error(request, "このセッションは現在入室できません。")
        return redirect("beon:sessions", category_id=session.category_id)

    assigned_roles = set(
        session.assignments.values_list("role", flat=True)
    )
    required_roles = {
        BeonSessionMember.Role.CHIEF,
        BeonSessionMember.Role.DIRECTOR,
        BeonSessionMember.Role.ANNOUNCER,
    }
    if assigned_roles != required_roles:
        messages.error(request, "担当者3名（チーフ・ディレクター・アナウンサー）の割当が完了していません。")
        return redirect("beon:sessions", category_id=session.category_id)

    try:
        with transaction.atomic():
            BeonPresence.release_stale(minutes=2)

            existing = BeonPresence.objects.filter(user=request.user).first()
            if existing and existing.session_id != session.pk:
                messages.error(
                    request,
                    f"すでに「{existing.session}」へ入室しています。先に退出してください。",
                )
                return redirect("beon:sessions", category_id=session.category_id)

            if existing:
                existing.last_seen = timezone.now()
                existing.save(update_fields=("last_seen",))
            else:
                BeonPresence.objects.create(
                    user=request.user,
                    session=session,
                    entered_at=timezone.now(),
                    last_seen=timezone.now(),
                )
    except IntegrityError:
        messages.error(request, "別のセッションへの入室が先に確定しました。")
        return redirect("beon:sessions", category_id=session.category_id)

    request.session["beon_session_id"] = session.pk
    return redirect("beon:index")


@login_required
def index(request):
    presence = (
        BeonPresence.objects
        .select_related("session", "session__category")
        .filter(user=request.user)
        .first()
    )
    if not presence:
        request.session.pop("beon_session_id", None)
        return redirect("beon:categories")

    if not BeonSessionMember.objects.filter(
        session=presence.session, user=request.user
    ).exists():
        presence.delete()
        request.session.pop("beon_session_id", None)
        return redirect("beon:categories")

    role = BeonSessionMember.objects.get(
        session=presence.session, user=request.user
    ).get_role_display()

    return render(request, "beon/index.html", {
        "current_session": presence.session,
        "current_role": role,
        "beon_current_session": presence.session,
        "beon_current_role": role,
    })


@login_required
@require_POST
def heartbeat(request):
    updated = BeonPresence.objects.filter(user=request.user).update(
        last_seen=timezone.now()
    )
    return JsonResponse({"ok": bool(updated)})


@login_required
@require_POST
def exit_session(request):
    BeonPresence.objects.filter(user=request.user).delete()
    request.session.pop("beon_session_id", None)
    return redirect("beon:categories")


@login_required
@require_POST
def next_session(request):
    current = get_object_or_404(
        BeonPresence.objects.select_related("session", "session__category"),
        user=request.user,
    ).session

    next_item = (
        BeonSession.objects.filter(
            category=current.category,
            order__gt=current.order,
            assignments__user=request.user,
            status__in=(BeonSession.Status.READY, BeonSession.Status.RUNNING),
        )
        .order_by("order", "id")
        .first()
    )
    if not next_item:
        messages.error(request, "次に参加できる担当セッションはありません。")
        return redirect("beon:index")

    required_roles = {
        BeonSessionMember.Role.CHIEF,
        BeonSessionMember.Role.DIRECTOR,
        BeonSessionMember.Role.ANNOUNCER,
    }
    if set(next_item.assignments.values_list("role", flat=True)) != required_roles:
        messages.error(request, "次のセッションは担当者の割当が完了していません。")
        return redirect("beon:index")

    # 退出と次セッションへの入室を同一トランザクションで処理する。
    try:
        with transaction.atomic():
            presence = BeonPresence.objects.select_for_update().get(user=request.user)
            presence.session = next_item
            presence.entered_at = timezone.now()
            presence.last_seen = timezone.now()
            presence.save(update_fields=("session", "entered_at", "last_seen"))
    except BeonPresence.DoesNotExist:
        return redirect("beon:categories")

    request.session["beon_session_id"] = next_item.pk
    return redirect("beon:index")


@login_required
@user_passes_test(lambda user: user.is_staff)
def assignment_edit(request, session_id):
    session = get_object_or_404(BeonSession, pk=session_id)
    initial = {}
    for item in session.assignments.select_related("user"):
        initial[item.role] = item.user

    form = SessionAssignmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save(session)
        messages.success(request, "担当者を更新しました。")
        return redirect("beon:index")

    return render(request, "beon/assignment_edit.html", {
        "session": session,
        "form": form,
    })


@login_required
def settings_page(request):
    return render(request, "beon/settings.html")


@login_required
def weather_page(request):
    # Yahoo! JAPAN気象情報APIの利用条件・認証情報を確認後に接続する。
    return render(request, "beon/weather.html")
