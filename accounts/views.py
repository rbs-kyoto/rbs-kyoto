from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect


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