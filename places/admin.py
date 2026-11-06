from django.contrib import admin

from .forms import PlaceForm
from .models import Place


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    form = PlaceForm
    list_display = ("__str__", "code", "is_venue", "is_storage", "is_active")
    list_filter = ("is_venue", "is_storage", "is_active")
    search_fields = ("name", "code", "description")

    def has_delete_permission(self, request, obj=None):
        return False
