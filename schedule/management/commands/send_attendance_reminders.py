"""出欠が未回答の割当部員へ、Web Push でリマインドを送る。

毎朝1回、サーバーのスケジューラーから実行する(deploy/attendance-reminders.md)。
対象は「出欠を取る」予定の、開始の3日前・前日・当日の回。回答済みの人には送らない。
"""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from accounts.push import PushConfigurationError, send_web_push
from schedule.models import Attendance, AttendanceReminderDelivery, Event
from schedule.recurrence import expand

# 開始の何日前に送るか(0 は当日)
REMINDER_DAYS_BEFORE = {3, 1, 0}
WEEKDAYS = "月火水木金土日"


def _when_label(days_until):
    return "本日" if days_until == 0 else f"あと{days_until}日"


def _event_time_label(occ):
    local = occ.start
    label = f"{local.month}月{local.day}日({WEEKDAYS[local.weekday()]})"
    if not occ.event.all_day:
        label += f" {local:%H:%M}"
    return label


class Command(BaseCommand):
    help = "出欠が未回答の割当部員へ、Web Push でリマインドを送る。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="送信せず、誰にどの通知を送る予定かだけを表示する。",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        today = timezone.localdate()
        horizon = today + timedelta(days=max(REMINDER_DAYS_BEFORE))

        events = list(
            Event.objects.filter(
                ask_attendance=True,
                assignments__isnull=False,
                start__date__lte=horizon,
            )
            .distinct()
            .prefetch_related("assignments__member__account__push_subscriptions")
        )
        answered = set(
            Attendance.objects.filter(
                assignment__event__in=events, date__gte=today
            ).values_list("assignment_id", "date")
        )

        sent = 0
        skipped_answered = 0
        failures = 0
        for occ in expand(events, today, horizon):
            days_until = (occ.first_day - today).days
            if days_until not in REMINDER_DAYS_BEFORE or occ.end < timezone.localtime(now):
                continue

            payload = {
                "title": "出欠のお願い",
                "body": (
                    f"「{occ.event.title}」{_event_time_label(occ)}の出欠が"
                    f"未回答です。（{_when_label(days_until)}）"
                ),
                "url": (
                    f"{reverse('schedule:event_detail', args=[occ.event.pk])}"
                    f"?date={occ.first_day.isoformat()}"
                ),
            }

            for assignment in occ.event.assignments.all():
                if (assignment.pk, occ.first_day) in answered:
                    skipped_answered += 1
                    continue
                account = assignment.member.account
                if account is None:
                    continue

                subscriptions = [
                    sub
                    for sub in account.push_subscriptions.all()
                    if sub.schedule_reminders_enabled
                ]
                for subscription in subscriptions:
                    already_sent = AttendanceReminderDelivery.objects.filter(
                        subscription=subscription,
                        assignment=assignment,
                        date=occ.first_day,
                        days_until=days_until,
                    ).exists()
                    if already_sent:
                        continue

                    if dry_run:
                        self.stdout.write(
                            f"[dry-run] {assignment.member.name} <- {payload['body']}"
                        )
                        sent += 1
                        continue

                    try:
                        delivered = send_web_push(subscription, payload)
                    except PushConfigurationError as error:
                        raise CommandError(
                            f"Web Push の設定を確認してください: {error}"
                        ) from error
                    except WebPushException as error:
                        failures += 1
                        status = (
                            error.response.status_code
                            if error.response is not None
                            else "unknown"
                        )
                        self.stderr.write(
                            f"Push failed for subscription {subscription.pk} (HTTP {status})."
                        )
                        continue
                    if not delivered:
                        # 端末の購読が失効していた(send_web_push が購読を削除済み)
                        continue

                    AttendanceReminderDelivery.objects.get_or_create(
                        subscription=subscription,
                        assignment=assignment,
                        date=occ.first_day,
                        days_until=days_until,
                    )
                    sent += 1

        if failures:
            raise CommandError(
                f"{failures} 件の送信に失敗しました（{sent} 件は送信済み）。"
            )
        summary = f"（回答済みのためスキップ: {skipped_answered} 件）"
        if dry_run:
            self.stdout.write(f"出欠リマインドの送信予定: {sent} 件{summary}")
        else:
            self.stdout.write(f"出欠リマインドを {sent} 件送信しました。{summary}")
