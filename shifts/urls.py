from django.urls import path
from . import views

app_name = "shifts"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("create/", views.event_create, name="event_create"),
    path("mine/", views.my_assignments, name="my_assignments"),
    path("roster/", views.roster, name="roster"),
    path("roster/import/", views.roster_import, name="roster_import"),
    path("<int:pk>/", views.event_detail, name="event_detail"),
    path("<int:pk>/assign/", views.event_assign, name="event_assign"),
    path("programs/<int:pk>/delete/", views.program_delete, name="program_delete"),
    path("assignments/<int:pk>/delete/", views.assignment_delete, name="assignment_delete"),
]
