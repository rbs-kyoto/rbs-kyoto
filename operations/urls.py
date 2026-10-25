from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("", views.index, name="index"),
    path("run/", views.run, name="run"),
    path("status/<str:request_id>/", views.status, name="status"),
]
