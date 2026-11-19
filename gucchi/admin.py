from django.contrib import admin

from .models import GucchiJob, Script, ScriptRevision


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "target_seconds", "created_at", "updated_at")
    search_fields = ("title", "source_text", "owner__username")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("owner",)


@admin.register(ScriptRevision)
class ScriptRevisionAdmin(admin.ModelAdmin):
    list_display = ("id", "script", "kind", "created_at")
    list_filter = ("kind",)
    readonly_fields = ("created_at",)


@admin.register(GucchiJob)
class GucchiJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "status",
        "owner",
        "queued_at",
        "started_at",
        "finished_at",
    )
    list_filter = ("kind", "status")
    search_fields = ("owner__username", "error")
    readonly_fields = (
        "queued_at",
        "started_at",
        "finished_at",
    )
