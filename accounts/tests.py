import json
import base64
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from py_vapid import Vapid
from pywebpush import WebPushException

from .push import PushConfigurationError, send_web_push
from equipment.models import Category, Equipment, ReturnRecord, UsageRecord
from roll.models import RosterEntry
from .models import NotificationHistory, WebPushSubscription
from .admin import (
    SuperuserGrantCredentialAdmin,
    SuperuserGrantCredentialAdminForm,
)
from .models import SuperuserGrantCredential


class SuperuserUnlockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member",
            password="Member-pass-123",
        )
        self.client.force_login(self.user)
        self.credential = SuperuserGrantCredential()
        self.credential.set_password("promotion-pass-123")
        self.credential.save()
        self.url = reverse("accounts:superuser_unlock")

    def test_correct_password_grants_persistent_superuser_access(self):
        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.is_staff)
        self.assertNotEqual(self.credential.password_hash, "promotion-pass-123")
        self.assertTrue(self.credential.check_password("promotion-pass-123"))

    def test_incorrect_password_does_not_grant_access(self):
        response = self.client.post(self.url, {"password": "incorrect"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_promotion_password_requires_a_login(self):
        self.client.logout()

        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_promotion_password_is_limited_to_five_failed_attempts_per_session(self):
        for _ in range(5):
            response = self.client.post(self.url, {"password": "incorrect"})
            self.assertEqual(response.status_code, 400)

        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 429)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_credential_admin_form_stores_only_a_password_hash(self):
        form = SuperuserGrantCredentialAdminForm(data={"password": "new-secret-pass"})

        self.assertTrue(form.is_valid(), form.errors)
        credential = form.save()

        self.assertNotEqual(credential.password_hash, "new-secret-pass")
        self.assertTrue(credential.check_password("new-secret-pass"))

    def test_credential_admin_is_superuser_only_and_singleton(self):
        model_admin = SuperuserGrantCredentialAdmin(
            SuperuserGrantCredential,
            admin.site,
        )
        request = RequestFactory().get("/admin/accounts/superusergrantcredential/")
        request.user = self.user
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Admin-pass-123",
        )
        request.user = admin_user
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertTrue(model_admin.has_change_permission(request))

    def test_superuser_can_change_the_credential_in_admin_without_reading_hash(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Admin-pass-123",
        )
        self.client.force_login(admin_user)
        change_url = reverse(
            "admin:accounts_superusergrantcredential_change",
            args=[self.credential.pk],
        )

        response = self.client.get(change_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="password"')
        self.assertNotContains(response, self.credential.password_hash)


class MypageEquipmentTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="borrower")
        self.other_user = user_model.objects.create_user(username="another-borrower")
        self.entry = RosterEntry.objects.create(
            name="本人",
            entry_type=RosterEntry.EntryType.STUDENT,
            account=self.user,
        )
        self.other_entry = RosterEntry.objects.create(
            name="別の人",
            entry_type=RosterEntry.EntryType.STUDENT,
            account=self.other_user,
        )
        category = Category.objects.get(code="A")
        self.equipment = Equipment.objects.create(
            category=category,
            inventory_number="A-MYPAGE-1",
            name="本人のマイク",
            quantity=2,
            unit="本",
        )
        self.own_usage = UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination=str(self.entry),
            destination_entry=self.entry,
            quantity=2,
        )
        UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination=str(self.other_entry),
            destination_entry=self.other_entry,
            quantity=1,
        )
        self.client.force_login(self.user)

    def test_mypage_lists_only_the_current_users_unreturned_equipment(self):
        ReturnRecord.objects.create(usage=self.own_usage, quantity=1)

        response = self.client.get(reverse("accounts:mypage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本人のマイク")
        self.assertContains(response, "未返却 1本")
        self.assertNotContains(response, "別の人")

    def test_mypage_does_not_show_fully_returned_equipment(self):
        ReturnRecord.objects.create(usage=self.own_usage, quantity=2)

        response = self.client.get(reverse("accounts:mypage"))

        self.assertNotContains(response, "本人のマイク")
        self.assertContains(response, "未返却の貸出・持出はありません。")

    def test_mypage_explains_when_roster_account_is_not_linked(self):
        self.client.force_login(get_user_model().objects.create_user(username="unlinked"))

        response = self.client.get(reverse("accounts:mypage"))

        self.assertContains(response, "Roll名簿とアカウントが連携されていない")

    def test_push_subscription_is_saved_for_current_user(self):
        response = self.client.post(
            reverse("accounts:push_subscription"),
            data=json.dumps(
                {
                    "endpoint": "https://fcm.googleapis.com/fcm/send/subscription",
                    "keys": {"p256dh": "public-key", "auth": "auth-secret"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        subscription = self.user.push_subscriptions.get()
        self.assertEqual(subscription.p256dh, "public-key")
        self.assertFalse(subscription.equipment_reminders_enabled)
        self.assertFalse(subscription.news_notifications_enabled)

    def test_push_subscription_rejects_non_push_service_endpoint(self):
        response = self.client.post(
            reverse("accounts:push_subscription"),
            data=json.dumps(
                {
                    "endpoint": "https://example.com/collect",
                    "keys": {"p256dh": "public-key", "auth": "auth-secret"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.user.push_subscriptions.exists())

    def test_push_subscription_cannot_be_taken_over_by_another_user(self):
        self.other_user.push_subscriptions.create(
            endpoint="https://fcm.googleapis.com/fcm/send/other",
            p256dh="other-public-key",
            auth="other-auth-secret",
        )

        response = self.client.post(
            reverse("accounts:push_subscription"),
            data=json.dumps(
                {
                    "endpoint": "https://fcm.googleapis.com/fcm/send/other",
                    "keys": {"p256dh": "public-key", "auth": "auth-secret"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)

    def test_push_preferences_are_independent_and_get_confirmation_push(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/preferences",
            p256dh="public-key",
            auth="auth-secret",
        )
        with patch("accounts.views.send_web_push", return_value=True) as send_push:
            response = self.client.post(
                reverse("accounts:push_subscription_preferences"),
                data=json.dumps(
                    {
                        "endpoint": subscription.endpoint,
                        "type": "news",
                        "enabled": True,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertTrue(subscription.equipment_reminders_enabled)
        self.assertTrue(subscription.news_notifications_enabled)
        send_push.assert_called_once_with(
            subscription,
            {
                "title": "通知がオンになりました！",
                "body": "早速確認してみましょう",
                "url": reverse("accounts:mypage"),
            },
        )

    def test_disabling_one_notification_does_not_change_the_other(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/disable",
            p256dh="public-key",
            auth="auth-secret",
            equipment_reminders_enabled=True,
            news_notifications_enabled=True,
        )

        response = self.client.post(
            reverse("accounts:push_subscription_preferences"),
            data=json.dumps(
                {
                    "endpoint": subscription.endpoint,
                    "type": "equipment",
                    "enabled": False,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertFalse(subscription.equipment_reminders_enabled)
        self.assertTrue(subscription.news_notifications_enabled)

    def test_failed_confirmation_does_not_enable_notification(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/failed",
            p256dh="public-key",
            auth="auth-secret",
            equipment_reminders_enabled=False,
        )
        with patch(
            "accounts.views.send_web_push",
            side_effect=WebPushException("Push delivery failed"),
        ):
            response = self.client.post(
                reverse("accounts:push_subscription_preferences"),
                data=json.dumps(
                    {
                        "endpoint": subscription.endpoint,
                        "type": "equipment",
                        "enabled": True,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 502)
        subscription.refresh_from_db()
        self.assertFalse(subscription.equipment_reminders_enabled)

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="",
        WEBPUSH_VAPID_PRIVATE_KEY="",
        WEBPUSH_VAPID_SUBJECT="",
    )
    def test_confirmation_requires_vapid_configuration(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/not-configured",
            p256dh="public-key",
            auth="auth-secret",
            news_notifications_enabled=False,
        )

        response = self.client.post(
            reverse("accounts:push_subscription_preferences"),
            data=json.dumps(
                {
                    "endpoint": subscription.endpoint,
                    "type": "news",
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        subscription.refresh_from_db()
        self.assertFalse(subscription.news_notifications_enabled)

    def test_preferences_endpoint_only_exposes_current_users_subscription(self):
        subscription = self.other_user.push_subscriptions.create(
            endpoint="https://fcm.googleapis.com/fcm/send/private-preferences",
            p256dh="public-key",
            auth="auth-secret",
        )

        response = self.client.get(
            reverse("accounts:push_subscription_preferences"),
            {"endpoint": subscription.endpoint},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"subscribed": False})


class WebPushConfigurationTests(TestCase):
    def setUp(self):
        self.vapid_key = Vapid()
        self.vapid_key.generate_keys()
        public_key_bytes = self.vapid_key.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        self.public_key = (
            base64.urlsafe_b64encode(public_key_bytes).decode("ascii").rstrip("=")
        )
        self.private_key = self.vapid_key.private_pem().decode("utf-8")
        self.subscription = SimpleNamespace(
            endpoint="https://fcm.googleapis.com/fcm/send/test",
            p256dh="p256dh",
            auth="auth",
        )

    @override_settings(WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com")
    @patch("accounts.push.webpush")
    def test_sends_with_matching_vapid_pem_keys(self, webpush_mock):
        with override_settings(
            WEBPUSH_VAPID_PUBLIC_KEY=self.public_key,
            WEBPUSH_VAPID_PRIVATE_KEY=self.private_key,
        ):
            result = send_web_push(self.subscription, {"title": "test"})

        self.assertTrue(result)
        self.assertIsInstance(webpush_mock.call_args.kwargs["vapid_private_key"], Vapid)

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="different-public-key",
        WEBPUSH_VAPID_PRIVATE_KEY="UCUKEHn7Jd33QZx5lJFKBY4plOxGsJ6xJSOzE14jQlo",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("accounts.push.webpush")
    def test_rejects_mismatched_vapid_public_and_private_keys(self, webpush_mock):
        with self.assertRaises(PushConfigurationError):
            send_web_push(self.subscription, {"title": "test"})

        webpush_mock.assert_not_called()

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="a" * 87,
        WEBPUSH_VAPID_PRIVATE_KEY="/missing/private-key.pem",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("accounts.push.webpush")
    def test_rejects_missing_vapid_private_key_file(self, webpush_mock):
        with self.assertRaises(PushConfigurationError):
            send_web_push(self.subscription, {"title": "test"})

        webpush_mock.assert_not_called()


class MypageNotificationHistoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="history-user")
        self.other_user = user_model.objects.create_user(username="history-other")
        self.client.force_login(self.user)

    def test_empty_history_shows_placeholder(self):
        response = self.client.get(reverse("accounts:mypage"))

        self.assertContains(response, "送信済みの通知はまだありません。")

    def test_shows_only_own_history_newest_first(self):
        NotificationHistory.objects.create(
            user=self.user,
            kind=NotificationHistory.Kind.NEWS,
            title="古い通知",
            body="古い本文",
            url="/news/1/",
        )
        NotificationHistory.objects.create(
            user=self.user,
            kind=NotificationHistory.Kind.EQUIPMENT,
            title="新しい通知",
            body="新しい本文",
            url="/equipment/usages/1/",
        )
        NotificationHistory.objects.create(
            user=self.other_user,
            kind=NotificationHistory.Kind.NEWS,
            title="他人の通知",
        )

        response = self.client.get(reverse("accounts:mypage"))

        content = response.content.decode()
        self.assertContains(response, 'href="/news/1/"')
        self.assertNotContains(response, "他人の通知")
        self.assertLess(content.index("新しい通知"), content.index("古い通知"))

    def test_shows_at_most_twenty_entries(self):
        for number in range(25):
            NotificationHistory.objects.create(
                user=self.user,
                kind=NotificationHistory.Kind.NEWS,
                title=f"通知{number:02d}",
            )

        response = self.client.get(reverse("accounts:mypage"))

        self.assertEqual(len(response.context["notification_history"]), 20)
        self.assertContains(response, "通知24")
        self.assertNotContains(response, "通知04")

    def test_escapes_notification_text(self):
        NotificationHistory.objects.create(
            user=self.user,
            kind=NotificationHistory.Kind.NEWS,
            title="<script>alert(1)</script>",
        )

        response = self.client.get(reverse("accounts:mypage"))

        self.assertNotContains(response, "<script>alert(1)</script>")
