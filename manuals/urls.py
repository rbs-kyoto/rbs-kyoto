from django.urls import path
from . import views

app_name = "manuals"

urlpatterns = [
    path("", views.manual_list, name="manual_list"),
    path("<int:pk>/", views.manual_detail, name="manual_detail"),
]
