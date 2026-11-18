from django.urls import path

from . import views

app_name = "beon"

urlpatterns = [
    path("", views.index, name="index"),
    path("categories/", views.category_list, name="categories"),
    path("categories/<int:category_id>/", views.session_list, name="sessions"),
    path("sessions/<int:session_id>/join/", views.join_session, name="join"),
    path("sessions/exit/", views.exit_session, name="exit"),
    path("sessions/next/", views.next_session, name="next"),
    path("sessions/heartbeat/", views.heartbeat, name="heartbeat"),
    path("sessions/<int:session_id>/assignments/", views.assignment_edit, name="assignment_edit"),
    path("settings/", views.settings_page, name="settings"),
    path("weather/", views.weather_page, name="weather"),
]
