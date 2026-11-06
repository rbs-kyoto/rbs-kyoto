from django.urls import path

from . import views

app_name = "roll"

urlpatterns = [
    path("", views.roster_list, name="list"),
    path("import/", views.import_csv, name="import_csv"),
]
