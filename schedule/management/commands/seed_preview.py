"""devbox などのプレビュー環境用に、管理者ユーザーとデモ予定を作る。

PREVIEW_ADMIN_PASSWORD が未設定ならユーザーは作らない(固定パスワードは持たない)。
何度実行しても、既存のユーザーや予定を重複して作らない。
"""

import os
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from roll.models import RosterEntry
from schedule.models import Assignment, Event

DEMO_TITLES = ("【デモ】定例会", "【デモ】撮影", "【デモ】合宿")


class Command(BaseCommand):
    help = "プレビュー用の管理者ユーザーとデモ予定を作成する"

    def handle(self, *args, **options):
        user = self._create_admin()
        self._create_events()
        self._create_assignments(user)

    def _create_admin(self):
        password = os.getenv("PREVIEW_ADMIN_PASSWORD", "")
        if not password:
            self.stdout.write("PREVIEW_ADMIN_PASSWORD が未設定のため、ユーザーは作りません。")
            return None

        username = os.getenv("PREVIEW_ADMIN_USERNAME", "preview")
        user, created = get_user_model().objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True},
        )
        # env を変えて再起動したときにパスワードが追従するよう、毎回設定する
        user.set_password(password)
        user.is_staff = user.is_superuser = True
        user.save()
        self.stdout.write(f"管理者ユーザー '{username}' を{'作成' if created else '更新'}しました。")
        return user

    def _create_events(self):
        if Event.objects.filter(title__in=DEMO_TITLES).exists():
            return

        today = timezone.localdate()

        def at(day, hour=0, minute=0):
            return timezone.make_aware(datetime.combine(day, time(hour, minute)))

        # 今週の水曜から毎週の定例会
        wednesday = today - timedelta(days=today.weekday()) + timedelta(days=2)
        Event.objects.create(
            title=DEMO_TITLES[0],
            start=at(wednesday, 16),
            end=at(wednesday, 17, 30),
            location="放送室",
            recurrence=Event.Recurrence.WEEKLY,
        )
        Event.objects.create(
            title=DEMO_TITLES[1],
            start=at(today + timedelta(days=1), 13),
            location="体育館",
            description="デモ用の予定です。",
        )
        Event.objects.create(
            title=DEMO_TITLES[2],
            start=at(today + timedelta(days=10)),
            end=at(today + timedelta(days=12)),
            all_day=True,
        )
        self.stdout.write("デモ予定を作成しました。")

    def _create_assignments(self, user):
        """割当部員と出欠を試せるよう、名簿の部員を割り当てる(管理者本人も部員にする)。"""
        event = Event.objects.filter(title=DEMO_TITLES[0]).first()
        if event is None or event.assignments.exists():
            return

        event.ask_attendance = True
        event.save(update_fields=["ask_attendance"])

        members = [
            ("【デモ】部員A", "司会", None),
            ("【デモ】部員B", "音声", None),
        ]
        if user is not None:
            members.insert(0, ("【デモ】プレビュー部員", "書記", user))

        for name, role, account in members:
            entry, _ = RosterEntry.objects.get_or_create(
                name=name, defaults={"is_member": True, "account": account}
            )
            Assignment.objects.get_or_create(event=event, member=entry, defaults={"role": role})
        self.stdout.write("デモの割当部員を作成しました(出欠はON)。")
