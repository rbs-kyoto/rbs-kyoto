from django.urls import path

from . import views

app_name = "video_archive"

urlpatterns = [
    path("", views.video_list, name="video_list"),
    path("year/<int:year>/", views.video_year_list, name="video_year_list"),
    path("<int:pk>/", views.video_detail, name="video_detail"),
]
