from django.core.management.base import BaseCommand

from gucchi.worker import run_next_job


class Command(BaseCommand):
    help = "ぐっちくんジョブを同時実行1件までで処理します"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        processed = run_next_job()
        if processed is None:
            self.stdout.write("処理対象のジョブはありません")
            return
        self.stdout.write(
            f"ジョブ {processed.pk}: {processed.get_status_display()} "
            f"({processed.get_kind_display()})"
        )
