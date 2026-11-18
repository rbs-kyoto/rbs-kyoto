from django.contrib import admin

from .models import (
    BeonCategory, BeonPresence, BeonSession, BeonSessionMember,
)


class BeonSessionMemberInline(admin.TabularInline):
    model = BeonSessionMember
    extra = 3


@admin.register(BeonCategory)
class BeonCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "event_date", "venue", "is_active", "order")
    list_editable = ("is_active", "order")
    search_fields = ("name", "venue")


@admin.register(BeonSession)
class BeonSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status", "order", "starts_at", "ends_at")
    list_filter = ("category", "status")
    list_editable = ("status", "order")
    search_fields = ("name", "category__name")
    inlines = (BeonSessionMemberInline,)


@admin.register(BeonPresence)
class BeonPresenceAdmin(admin.ModelAdmin):
    list_display = ("user", "session", "entered_at", "last_seen")
    readonly_fields = ("user", "session", "entered_at", "last_seen")


@admin.register(BeonSessionMember)
class BeonSessionMemberAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "user")
    list_filter = ("role", "session__category")
    search_fields = ("user__username", "user__email", "session__name")
