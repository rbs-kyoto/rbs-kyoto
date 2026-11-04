from django.contrib import admin

from .models import Position, RosterEntry


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("name",)
    ordering = ("order", "name")


@admin.register(RosterEntry)
class RosterEntryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "entry_type",
        "grade",
        "homeroom",
        "student_number",
        "is_member",
        "account",
    )
    list_filter = ("entry_type", "is_member", "positions")
    list_editable = ("is_member",)
    search_fields = ("name", "name_kana", "school_identifier", "grade", "homeroom")
    filter_horizontal = ("positions",)
    autocomplete_fields = ("account",)
