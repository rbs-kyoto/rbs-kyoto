from django.urls import path

from . import views

app_name = "places"

urlpatterns = [
    path("", views.place_list, name="list"),
    path("create/", views.place_create, name="create"),
    path("<int:pk>/edit/", views.place_edit, name="edit"),
]
