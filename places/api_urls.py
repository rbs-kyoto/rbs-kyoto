from django.urls import path

from . import api

app_name = "places_api"

urlpatterns = [
    path("", api.place_list, name="list"),
    path("<int:pk>/", api.place_detail, name="detail"),
    path("<int:pk>/usage/", api.place_usage, name="usage"),
]
