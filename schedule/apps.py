from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    name = 'schedule'

    def ready(self):
        # 場所マスターに、予定の利用状況を提供する(競合チェックに使われる)
        from places.registry import register_provider

        from .place_usage import provide

        register_provider("schedule", provide)
