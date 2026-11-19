from django.urls import path

from . import views


app_name = "revise"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.new_post, name="new"),
    path("<int:post_id>/", views.detail, name="detail"),
    path("<int:post_id>/proofread/", views.proofread, name="proofread"),
    path("<int:post_id>/close/", views.toggle_close, name="toggle_close"),
    path("pairs/", views.learning_pair_queue, name="pairs"),
]
