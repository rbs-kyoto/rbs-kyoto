from django.urls import path

from . import views

app_name = "publisher"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("deploy/", views.deploy, name="deploy"),
    path("versions/<int:version>/activate/", views.activate, name="activate"),
    path("preview/<str:variant>/", views.preview, name="preview"),
    path("preview/<str:variant>/<path:path>", views.preview, name="preview"),
]
