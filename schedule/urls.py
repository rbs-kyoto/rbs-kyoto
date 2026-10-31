from django.urls import path
from . import views

app_name = "schedule"

urlpatterns = [
    path("", views.calendar_month, name="calendar"),
    path("create/", views.event_create, name="event_create"),
    path("<int:pk>/", views.event_detail, name="event_detail"),
    path("<int:pk>/edit/", views.event_edit, name="event_edit"),
    path("<int:pk>/delete/", views.event_delete, name="event_delete"),
]
