from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from publisher.admin_ui import LivePreviewMixin
from .models import Video, VideoGroup


@admin.register(VideoGroup)
class VideoGroupAdmin(ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")


@admin.register(Video)
class VideoAdmin(LivePreviewMixin, ModelAdmin):
    list_display = (
        "thumbnail_image",
        "title",
        "group",
        "has_subtitles",
        "event_date",
        "production_date",
        "order",
        "is_active",
    )
    list_display_links = ("thumbnail_image", "title")
    list_filter = ("group", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("title", "description")

    @admin.display(description="サムネイル")
    def thumbnail_image(self, obj):
        url = obj.thumbnail.url if obj.thumbnail else obj.youtube_thumbnail_url
        if not url:
            return "—"
        return format_html('<img src="{}" alt="" style="height:2.5rem;border-radius:.25rem">', url)
