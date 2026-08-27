from django.contrib import admin
from .models import Manual


@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active", "uploaded_at")
    list_editable = ("order", "is_active")
    ordering = ("order",)
