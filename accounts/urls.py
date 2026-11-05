from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("mypage/", views.mypage, name="mypage"),
    path("push-subscription/", views.save_push_subscription, name="push_subscription"),
    path(
        "push-subscription/delete/",
        views.delete_push_subscription,
        name="delete_push_subscription",
    ),
    path(
        "push-subscription/preferences/",
        views.push_subscription_preferences,
        name="push_subscription_preferences",
    ),
    path("superuser-unlock/", views.superuser_unlock, name="superuser_unlock"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("password/change/", views.password_change, name="password_change"),

    path(
        "google/link-confirm/",
        views.google_link_confirm,
        name="google_link_confirm",
    ),
]