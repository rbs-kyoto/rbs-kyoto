from django.core.management.base import BaseCommand

from system_status.checks import refresh
from system_status.models import Level


class Command(BaseCommand):
    help = "「システムの状態」の各項目を確認して保存します。"

    def handle(self, *args, **options):
        status = refresh()
        for item in status.results:
            self.stdout.write(f"[{Level(item['level']).label}] {item['label']}: {item['value']} {item['detail']}")
