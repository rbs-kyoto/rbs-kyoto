import json
from json import JSONDecodeError
from urllib.parse import urlsplit

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.account.utils import perform_login
from pywebpush import WebPushException
from equipment.models import UsageRecord
from roll.models import RosterEntry
from .push import PushConfigurationError, send_web_push
from .models import (
    NotificationHistory,
    SuperuserGrantCredential,
    User,
    WebPushSubscription,
)
from urllib.parse import urlsplit
from django.utils.http import url_has_allowed_host_and_scheme


def get_login_redirect_url(request):
    next_url = request.POST.get("next") or request.GET.get("next")

    allowed_hosts = {
        urlsplit(url).netloc
        for url in settings.LOGIN_REDIRECT_ALLOWED_HOSTS
    }

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts=allowed_hosts,
        require_https=request.is_secure(),
    ):
        return next_url

    return reverse("accounts:mypage")


def login_view(request):
    redirect_url = get_login_redirect_url(request)

    if request.user.is_authenticated:
        return redirect(redirect_url)

    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)
            return redirect(redirect_url)

        return render(
            request,
            "accounts/login.html",
            {
                "error": "ユーザー名またはパスワードが正しくありません。",
                "next": request.POST.get("next", ""),
            },
        )

    return render(
        request,
        "accounts/login.html",
        {
            "next": request.GET.get("next", ""),
        },
    )

@login_required
def mypage(request):
    usages = (
        UsageRecord.objects.filter(destination_entry__account=request.user)
        .select_related("equipment", "destination_entry")
        .prefetch_related("returns")
        .order_by("due_at", "started_at", "pk")
    )
    open_usages = [usage for usage in usages if usage.remaining_quantity]
    return render(
        request,
        "accounts/mypage.html",
        {
            "open_usages": open_usages,
            "has_roster_entry": RosterEntry.objects.filter(
                account=request.user
            ).exists(),
            "notification_history": NotificationHistory.objects.filter(
                user=request.user
            )[:20],
            "webpush_public_key": (
                settings.WEBPUSH_VAPID_PUBLIC_KEY
                if all(
                    (
                        settings.WEBPUSH_VAPID_PUBLIC_KEY,
                        settings.WEBPUSH_VAPID_PRIVATE_KEY,
                        settings.WEBPUSH_VAPID_SUBJECT,
                    )
                )
                else ""
            ),
        },
    )


def _is_supported_push_endpoint(endpoint):
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
    ):
        return False
    host = hostname.lower().rstrip(".")
    return host in {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    } or host.endswith(".notify.windows.com")


@login_required
@require_POST
def save_push_subscription(request):
    try:
        payload = json.loads(request.body)
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "通知設定を読み取れませんでした。"}, status=400)

    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    keys = payload.get("keys") if isinstance(payload, dict) else None
    p256dh = keys.get("p256dh") if isinstance(keys, dict) else None
    auth = keys.get("auth") if isinstance(keys, dict) else None
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 2048
        or not _is_supported_push_endpoint(endpoint)
        or not isinstance(p256dh, str)
        or not p256dh
        or len(p256dh) > 200
        or not isinstance(auth, str)
        or not auth
        or len(auth) > 100
    ):
        return JsonResponse({"error": "通知設定の内容が正しくありません。"}, status=400)

    subscription = WebPushSubscription.objects.filter(endpoint=endpoint).first()
    if subscription and subscription.user_id != request.user.pk:
        return JsonResponse(
            {"error": "この端末の通知設定は別のアカウントに登録されています。"},
            status=409,
        )
    if subscription is None:
        subscription = WebPushSubscription(
            user=request.user,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            equipment_reminders_enabled=False,
            news_notifications_enabled=False,
            schedule_reminders_enabled=False,
        )
    else:
        subscription.p256dh = p256dh
        subscription.auth = auth
    try:
        subscription.save()
    except IntegrityError:
        return JsonResponse(
            {"error": "この端末の通知設定を保存できませんでした。再度お試しください。"},
            status=409,
        )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def delete_push_subscription(request):
    try:
        payload = json.loads(request.body)
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "通知設定を読み取れませんでした。"}, status=400)

    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return JsonResponse({"error": "通知設定の内容が正しくありません。"}, status=400)
    WebPushSubscription.objects.filter(
        user=request.user,
        endpoint=endpoint,
    ).delete()
    return JsonResponse({"ok": True})


@login_required
def push_subscription_preferences(request):
    endpoint = request.GET.get("endpoint", "")
    if request.method == "GET":
        if not endpoint or len(endpoint) > 2048:
            return JsonResponse(
                {"error": "端末の通知設定を確認できませんでした。"}, status=400
            )
        subscription = WebPushSubscription.objects.filter(
            user=request.user,
            endpoint=endpoint,
        ).first()
        if subscription is None:
            return JsonResponse({"subscribed": False})
        return JsonResponse(
            {
                "subscribed": True,
                "equipment_reminders_enabled": (
                    subscription.equipment_reminders_enabled
                ),
                "news_notifications_enabled": subscription.news_notifications_enabled,
                "schedule_reminders_enabled": subscription.schedule_reminders_enabled,
            }
        )

    if request.method != "POST":
        return JsonResponse({"error": "許可されていない操作です。"}, status=405)
    try:
        payload = json.loads(request.body)
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "通知設定を読み取れませんでした。"}, status=400)

    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    notification_type = payload.get("type") if isinstance(payload, dict) else None
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    preference_fields = {
        "equipment": "equipment_reminders_enabled",
        "news": "news_notifications_enabled",
        "schedule": "schedule_reminders_enabled",
    }
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 2048
        or not isinstance(notification_type, str)
        or notification_type not in preference_fields
        or not isinstance(enabled, bool)
    ):
        return JsonResponse({"error": "通知設定の内容が正しくありません。"}, status=400)

    subscription = WebPushSubscription.objects.filter(
        user=request.user,
        endpoint=endpoint,
    ).first()
    if subscription is None:
        return JsonResponse(
            {"error": "この端末の通知設定が見つかりません。"}, status=404
        )

    field_name = preference_fields[notification_type]
    if enabled:
        try:
            delivered = send_web_push(
                subscription,
                {
                    "title": "通知がオンになりました！",
                    "body": "早速確認してみましょう",
                    "url": reverse("accounts:mypage"),
                },
            )
        except PushConfigurationError:
            return JsonResponse(
                {
                    "error": (
                        "Push通知のVAPID鍵設定を確認してください。"
                        "開発環境の秘密鍵ファイルが見つからないか、公開鍵と一致していません。"
                    )
                },
                status=503,
            )
        except WebPushException:
            return JsonResponse(
                {"error": "確認通知を送信できませんでした。時間をおいて再度お試しください。"},
                status=502,
            )
        if not delivered:
            return JsonResponse(
                {"error": "この端末の通知購読が期限切れです。再度有効にしてください。"},
                status=410,
            )
    setattr(subscription, field_name, enabled)
    subscription.save(update_fields=[field_name, "updated_at"])
    return JsonResponse({"ok": True, "enabled": enabled})


@login_required
@require_POST
def superuser_unlock(request):
    if request.user.is_superuser:
        return JsonResponse({"ok": True, "message": "すでにスーパーユーザーです。"})

    attempts = request.session.get("superuser_unlock_attempts", 0)
    if attempts >= 5:
        return JsonResponse(
            {"ok": False, "message": "試行回数の上限に達しました。再ログインしてからお試しください。"},
            status=429,
        )

    password = request.POST.get("password", "")
    credential = SuperuserGrantCredential.objects.filter(pk=1).first()
    if credential is None:
        return JsonResponse(
            {"ok": False, "message": "昇格パスワードが設定されていません。"},
            status=503,
        )

    if not password or not credential.check_password(password):
        request.session["superuser_unlock_attempts"] = attempts + 1
        return JsonResponse(
            {"ok": False, "message": "パスワードが正しくありません。"},
            status=400,
        )

    request.session.pop("superuser_unlock_attempts", None)
    request.user.is_staff = True
    request.user.is_superuser = True
    request.user.save(update_fields=["is_staff", "is_superuser"])
    return JsonResponse({"ok": True, "message": "スーパーユーザー権限を付与しました。"})


@login_required
def profile_edit(request):
    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        email = request.POST.get("email", "").strip()
        request.user.display_name = display_name
        request.user.email = email
        request.user.save()

        return redirect("accounts:mypage")

    return render(request, "accounts/profile_edit.html")

@login_required
def password_change(request):
    error = None

    if request.method == "POST":
        current_password = request.POST.get("current_password", "")
        new_password = request.POST.get("new_password", "")
        new_password_confirm = request.POST.get("new_password_confirm", "")

        if not request.user.check_password(current_password):
            error = "現在のパスワードが正しくありません。"

        elif new_password != new_password_confirm:
            error = "新しいパスワードが一致していません。"

        else:
            try:
                validate_password(new_password, request.user)
            except ValidationError as e:
                error = " ".join(e.messages)

        if error is None:
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)

            return redirect("accounts:mypage")

    return render(
        request,
        "accounts/password_change.html",
        {"error": error},
    )

def logout_view(request):
    logout(request)
    return redirect("accounts:login")

def google_link_confirm(request):
    sociallogin_data = request.session.get("google_link_sociallogin")
    user_id = request.session.get("google_link_user_id")

    if not sociallogin_data or not user_id:
        return redirect("accounts:login")

    try:
        user = User.objects.get(pk=user_id)
        sociallogin = SocialLogin.deserialize(sociallogin_data)
    except (User.DoesNotExist, ValueError, KeyError):
        request.session.pop("google_link_sociallogin", None)
        request.session.pop("google_link_user_id", None)
        return redirect("accounts:login")

    email = (sociallogin.user.email or "").lower().strip()

    if not email.endswith("@rakunan-h.ed.jp"):
        request.session.pop("google_link_sociallogin", None)
        request.session.pop("google_link_user_id", None)
        messages.error(
            request,
            "権限がありません。組織管理（末尾が @rakunan-h.ed.jp）のアカウントでログインしてください。",
        )

        return redirect("accounts:login")

    if SocialAccount.objects.filter(
        user=user,
        provider="google",
    ).exists():
        request.session.pop("google_link_sociallogin", None)
        request.session.pop("google_link_user_id", None)

        messages.error(
            request,
            "このユーザーにはすでにGoogleアカウントが紐付いています。",
        )

        return redirect("accounts:login")

    if request.method == "POST":
        if request.POST.get("action") == "cancel":
            request.session.pop("google_link_sociallogin", None)
            request.session.pop("google_link_user_id", None)

            return redirect("accounts:login")

        if request.POST.get("action") == "confirm":
            sociallogin.connect(request, user)
            user.email = email
            if not user.is_staff:
                user.is_staff = True
                user.save(update_fields=["is_staff"])
            request.session.pop("google_link_sociallogin", None)
            request.session.pop("google_link_user_id", None)
            return perform_login(
                request,
                user,
                redirect_url=reverse("accounts:mypage"),
            )

    return render(
        request,
        "accounts/google_link_confirm.html",
        {
            "user": user,
            "google_email": email,
        },
    )