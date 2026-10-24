from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.account.utils import perform_login
from .models import User


def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:mypage")

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
            return redirect("accounts:mypage")

        return render(
            request,
            "accounts/login.html",
            {"error": "ユーザー名またはパスワードが正しくありません。"},
        )

    return render(request, "accounts/login.html")

@login_required
def mypage(request):
    return render(request, "accounts/mypage.html")


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