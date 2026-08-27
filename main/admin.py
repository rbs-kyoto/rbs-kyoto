from django.contrib import admin
from .models import Pickup, News

@admin.register(Pickup)
class PickupAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active")
    list_editable = ("order", "is_active")
    ordering = ("order",)

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "category", "is_active", "is_internal")
    list_filter = ("category", "is_active")
    list_editable = ("is_active",)
    ordering = ("-date",)

