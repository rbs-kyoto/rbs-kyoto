from django.contrib import admin
from .models import Role, Event, Program, Assignment


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")


class ProgramInline(admin.TabularInline):
    model = Program
    extra = 1
    fields = ("name", "order")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "is_active")
    list_editable = ("is_active",)
    ordering = ("-date",)
    inlines = [ProgramInline]


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 1
    autocomplete_fields = ["member"]
    fields = ("role", "member")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "order")
    list_filter = ("event",)
    ordering = ("event", "order")
    inlines = [AssignmentInline]
