from django.urls import path

from . import views

app_name = "system_status"

urlpatterns = [
    path("", views.status, name="status"),
    path("check/", views.check_now, name="check_now"),
    path("notes/", views.update_notes, name="update_notes"),
]
