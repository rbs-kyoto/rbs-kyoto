from django.contrib import admin
from unfold.admin import ModelAdmin
from publisher.admin_ui import LivePreviewMixin
from .models import Manual


@admin.register(Manual)
class ManualAdmin(LivePreviewMixin, ModelAdmin):
    list_display = ("title", "order", "is_active", "uploaded_at")
    list_editable = ("order", "is_active")
    search_fields = ("title", "content")
    ordering = ("order",)
