from django.urls import path
from . import views

app_name = "shifts"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("mine/", views.my_assignments, name="my_assignments"),
    path("<int:pk>/", views.event_detail, name="event_detail"),
]
