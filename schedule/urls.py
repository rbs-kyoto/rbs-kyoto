from django.urls import path
from . import views

app_name = "schedule"

urlpatterns = [
    path("", views.calendar_month, name="calendar"),
    path("week/", views.calendar_week, name="week"),
    path("create/", views.event_create, name="event_create"),
    path("<int:pk>/", views.event_detail, name="event_detail"),
    path("<int:pk>/respond/", views.event_respond, name="event_respond"),
    path("<int:pk>/edit/", views.event_edit, name="event_edit"),
    path("<int:pk>/delete/", views.event_delete, name="event_delete"),
]
