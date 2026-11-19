from django.contrib import admin

from .models import (
    LearningPair,
    ManualRevision,
    ProofreadRole,
    ReviseComment,
    RevisePost,
)


@admin.register(ProofreadRole)
class ProofreadRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "granted_at")
    search_fields = ("user__username", "user__display_name")


@admin.register(RevisePost)
class RevisePostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "status", "is_practice", "created_at")
    list_filter = ("status", "is_practice")
    search_fields = ("title", "body", "instruction", "author__username")


@admin.register(ReviseComment)
class ReviseCommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "created_at")
    search_fields = ("body", "author__username")


@admin.register(ManualRevision)
class ManualRevisionAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "created_at")
    search_fields = ("post__title", "author__username")


@admin.register(LearningPair)
class LearningPairAdmin(admin.ModelAdmin):
    list_display = ("before_text", "after_text", "rule_codes", "status", "reviewed_by")
    list_filter = ("status",)
