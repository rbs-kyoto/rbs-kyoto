from django.urls import path
from . import views

app_name = "main"

urlpatterns = [
    path("", views.index, name="index"),
    path("about/", views.about, name="about"),
    path("news/", views.news_all, name="news_all"),
    path("news/create/", views.news_create, name="news_create"),
    path("news/<int:pk>/", views.news_detail, name="news_detail"),
    path("news/<int:pk>/edit/", views.news_edit, name="news_edit"),
]