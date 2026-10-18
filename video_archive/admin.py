from django.contrib import admin
from .models import Video, VideoGroup


@admin.register(VideoGroup)
class VideoGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "group",
        "has_subtitles",
        "event_date",
        "production_date",
        "order",
        "is_active",
    )
    list_filter = ("group", "is_active")
    list_editable = ("order", "is_active")
