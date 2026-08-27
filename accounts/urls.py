from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("mypage/", views.mypage, name="mypage"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("password/change/", views.password_change, name="password_change"),

    path(
        "google/link-confirm/",
        views.google_link_confirm,
        name="google_link_confirm",
    ),
]