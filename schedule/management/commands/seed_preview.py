"""devbox などのプレビュー環境用に、管理者ユーザーとデモ予定を作る。

PREVIEW_ADMIN_PASSWORD が未設定ならユーザーは作らない(固定パスワードは持たない)。
何度実行しても、既存のユーザーや予定を重複して作らない。
"""

import os
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from equipment.models import Category, Equipment
from places.models import Place
from roll.models import Position, RosterEntry
from schedule.models import Assignment, Event, EventEquipment

DEMO_TITLES = ("【デモ】定例会", "【デモ】撮影", "【デモ】合宿")


class Command(BaseCommand):
    help = "プレビュー用の管理者ユーザーとデモ予定を作成する"

    def handle(self, *args, **options):
        user = self._create_admin()
        self._create_events()
        self._create_assignments(user)
        self._create_roster()
        self._create_equipment()

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

    def _place(self, name):
        """予定の場所として使える、デモ用の場所(なければ作る)。"""
        place, _ = Place.objects.get_or_create(
            name=name, parent=None, defaults={"is_venue": True, "is_storage": False}
        )
        return place

    def _create_events(self):
        if Event.objects.filter(title__in=DEMO_TITLES).exists():
            return

        today = timezone.localdate()
        studio = self._place("【デモ】放送室")
        gym = self._place("【デモ】体育館")

        def at(day, hour=0, minute=0):
            return timezone.make_aware(datetime.combine(day, time(hour, minute)))

        # 今週の水曜から毎週の定例会
        wednesday = today - timedelta(days=today.weekday()) + timedelta(days=2)
        Event.objects.create(
            title=DEMO_TITLES[0],
            start=at(wednesday, 16),
            end=at(wednesday, 17, 30),
            place=studio,
            recurrence=Event.Recurrence.WEEKLY,
        )
        Event.objects.create(
            title=DEMO_TITLES[1],
            start=at(today + timedelta(days=1), 13),
            place=gym,
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

    def _create_equipment(self):
        """機材の紐付けと「予約OK/競合」の表示を試せるよう、デモ機材を予定に結ぶ。"""
        category = Category.objects.order_by("code").first()
        if category is None:
            return

        mic, _ = Equipment.objects.get_or_create(
            inventory_number="PREVIEW-MIC",
            defaults={"category": category, "name": "【デモ】ワイヤレスマイク", "quantity": 2, "unit": "本"},
        )
        tripod, _ = Equipment.objects.get_or_create(
            inventory_number="PREVIEW-TRIPOD",
            defaults={"category": category, "name": "【デモ】三脚", "quantity": 3, "unit": "本"},
        )

        meeting = Event.objects.filter(title=DEMO_TITLES[0]).first()
        shoot = Event.objects.filter(title=DEMO_TITLES[1]).first()
        if meeting and not meeting.equipment_items.exists():
            EventEquipment.objects.create(event=meeting, equipment=mic, quantity=1)
        if shoot and not shoot.equipment_items.exists():
            EventEquipment.objects.create(event=shoot, equipment=mic, quantity=2)
            EventEquipment.objects.create(event=shoot, equipment=tripod, quantity=2)
        self.stdout.write("デモの使用機材を設定しました。")

    def _create_roster(self):
        """名簿の表のフィルター・一括選択、割当のコピーを試せるよう、学年・組・役職つきのデモ部員を足す。"""
        positions = {
            name: Position.objects.get_or_create(name=f"【デモ】{name}")[0]
            for name in ("部長", "撮影係", "音声係")
        }
        members = [
            ("【デモ】1年A", "1", "1", ["撮影係"]),
            ("【デモ】1年B", "1", "2", ["音声係"]),
            ("【デモ】2年A", "2", "3", ["部長"]),
            ("【デモ】2年B", "2", "3", ["撮影係"]),
            ("【デモ】3年A", "3", "1", []),
            ("【デモ】3年B", "3", "2", ["音声係", "撮影係"]),
        ]
        for name, grade, homeroom, position_names in members:
            entry, created = RosterEntry.objects.get_or_create(
                name=name,
                defaults={"is_member": True, "grade": grade, "homeroom": homeroom},
            )
            if created:
                entry.positions.set([positions[n] for n in position_names])
        self.stdout.write("デモの部員(学年・組・役職つき)を設定しました。")
