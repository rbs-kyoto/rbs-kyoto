from django.urls import path
from . import views

app_name = "main"

urlpatterns = [
    path("", views.index, name="index"),
    path("news/", views.news_all, name="news_all"),
    path("news/<int:pk>/", views.news_detail, name="news_detail"),
]