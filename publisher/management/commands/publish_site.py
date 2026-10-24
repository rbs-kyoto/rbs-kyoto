from django.core.management.base import BaseCommand, CommandError

from publisher import builder
from publisher.models import Deployment


class Command(BaseCommand):
    help = "公開サイトを静的に書き出して、新しいバージョンとして公開します。"

    def add_arguments(self, parser):
        parser.add_argument("-m", "--description", default="", help="デプロイの説明")

    def handle(self, *args, description, **options):
        deployment = builder.deploy(description=description)
        if deployment.status != Deployment.Status.READY:
            raise CommandError(deployment.error)
        self.stdout.write(
            self.style.SUCCESS(
                f"バージョン {deployment.version} を公開しました（{deployment.page_count}ページ）。"
            )
        )
