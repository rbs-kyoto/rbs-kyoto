from django.contrib import admin

from .models import MaintenanceSetting


@admin.register(MaintenanceSetting)
class MaintenanceSettingAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "運用状態",
            {
                "fields": (
                    "mode",
                    "announcement",
                )
            },
        ),
        (
            "計画メンテナンス",
            {
                "fields": (
                    "starts_at",
                    "resume_at",
                    "auto_resume_at",
                    "recovery_in_progress",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser
