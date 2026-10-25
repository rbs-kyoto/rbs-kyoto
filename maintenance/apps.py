from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maintenance"
    verbose_name = "メンテナンス"

    def ready(self):
        from django.db.models.signals import post_save

        from .models import MaintenanceSetting
        from .signals import send_schedule

        post_save.connect(send_schedule, sender=MaintenanceSetting, dispatch_uid="maintenance-send-schedule")
