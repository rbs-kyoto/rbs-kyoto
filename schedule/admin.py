from django.contrib import admin
from .models import Assignment, Attendance, Event, EventEquipment, UsageLink


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0


class EventEquipmentInline(admin.TabularInline):
    model = EventEquipment
    extra = 0


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    inlines = [AssignmentInline, EventEquipmentInline]
    list_display = ("title", "start", "end", "all_day", "recurrence", "ask_attendance")
    list_filter = ("recurrence", "all_day")
    search_fields = ("title", "location", "description")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("assignment", "date", "status", "comment", "responded_at")
    list_filter = ("status", "date")


@admin.register(UsageLink)
class UsageLinkAdmin(admin.ModelAdmin):
    list_display = ("item", "date", "usage")
