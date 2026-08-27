from django.urls import path
from . import views

app_name = "manuals"

urlpatterns = [
    path("", views.manual_list, name="manual_list"),
    path("create/", views.manual_create, name="manual_create"),
    path("<int:pk>/", views.manual_detail, name="manual_detail"),
    path("<int:pk>/edit/", views.manual_edit, name="manual_edit"),
]
