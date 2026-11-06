from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException
from requests import RequestException

from accounts.push import PushConfigurationError, send_web_push
from equipment.models import EquipmentReminderDelivery, UsageRecord


REMINDER_DAYS_BEFORE_DUE = {7, 3, 1, 0}


def reminder_days_until_due(days_until_due):
    if days_until_due in REMINDER_DAYS_BEFORE_DUE:
        return True
    return days_until_due < 0 and days_until_due % 3 == 0


class Command(BaseCommand):
    help = "Send Web Push reminders for equipment due dates."

    def handle(self, *args, **options):
        if not all(
            (
                settings.WEBPUSH_VAPID_PUBLIC_KEY,
                settings.WEBPUSH_VAPID_PRIVATE_KEY,
                settings.WEBPUSH_VAPID_SUBJECT,
            )
        ):
            raise CommandError(
                "Set WEBPUSH_VAPID_PUBLIC_KEY, WEBPUSH_VAPID_PRIVATE_KEY, "
                "and WEBPUSH_VAPID_SUBJECT before sending reminders."
            )

        today = timezone.localdate()
        usages = (
            UsageRecord.objects.filter(
                due_at__date__lte=today + timedelta(days=7),
                destination_entry__account__push_subscriptions__isnull=False,
                destination_entry__account__push_subscriptions__equipment_reminders_enabled=True,
            )
            .select_related("equipment", "destination_entry__account")
            .prefetch_related(
                "returns",
                "destination_entry__account__push_subscriptions",
            )
            .distinct()
        )
        sent_count = 0
        failure_count = 0
        for usage in usages:
            if not usage.remaining_quantity:
                continue
            due_date = timezone.localtime(usage.due_at).date()
            days_until_due = (due_date - today).days
            if not reminder_days_until_due(days_until_due):
                continue

            title = "リマインダー"
            if days_until_due > 0:
                body = f"「{usage.equipment.name}」の返却期限まであと{days_until_due}日です。"
            elif days_until_due == 0:
                body = f"「{usage.equipment.name}」の返却期限は本日です！"
            else:
                body = f"「{usage.equipment.name}」の返却期限を過ぎています！"
            payload = (
                {
                    "title": title,
                    "body": (
                        f"{body} "
                        f"未返却：{usage.remaining_quantity}{usage.equipment.unit}"
                    ),
                    "url": reverse("equipment:usage_detail", args=[usage.pk]),
                }
            )

            subscriptions = usage.destination_entry.account.push_subscriptions.all()
            for subscription in subscriptions:
                already_sent = EquipmentReminderDelivery.objects.filter(
                    subscription=subscription,
                    usage=usage,
                    due_at_snapshot=usage.due_at,
                    days_until_due=days_until_due,
                ).exists()
                if already_sent:
                    continue

                try:
                    delivered = send_web_push(subscription, payload)
                except PushConfigurationError as error:
                    raise CommandError(str(error)) from error
                except (WebPushException, RequestException) as error:
                    response = getattr(error, "response", None)
                    status_code = getattr(response, "status_code", None)
                    failure_count += 1
                    self.stderr.write(
                        f"Push failed for subscription {subscription.pk} "
                        f"(HTTP {status_code or 'unknown'})."
                    )
                    continue
                if not delivered:
                    # send_web_push already removed the expired subscription.
                    continue

                EquipmentReminderDelivery.objects.get_or_create(
                    subscription=subscription,
                    usage=usage,
                    due_at_snapshot=usage.due_at,
                    days_until_due=days_until_due,
                )
                sent_count += 1

        if failure_count:
            raise CommandError(
                f"{failure_count} Web Push delivery/deliveries failed; "
                f"{sent_count} reminder(s) sent."
            )
        self.stdout.write(f"Sent {sent_count} equipment reminder(s).")
