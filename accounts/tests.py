import json
import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from accounts.testing import make_member
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from allauth.socialaccount.models import SocialAccount
from py_vapid import Vapid
from pywebpush import WebPushException

from .adapters import ClosedSignupAccountAdapter, RakunanSocialAccountAdapter
from .audience import (
    Audience,
    audience_of,
    can_view,
    is_club_editor,
    is_club_member,
    is_outside_school,
    is_school_non_member,
    visible_audiences,
)
from .push import PushConfigurationError, send_web_push
from equipment.models import Category, Equipment, ReturnRecord, UsageRecord
from roll.models import RosterEntry
from .models import FailedAttempt, NotificationHistory, WebPushSubscription
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
        make_member(self.user)
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

    def test_promotion_password_is_limited_to_five_failed_attempts_per_account(self):
        for _ in range(5):
            response = self.client.post(self.url, {"password": "incorrect"})
            self.assertEqual(response.status_code, 400)

        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 429)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_promotion_limit_survives_logging_in_again(self):
        for _ in range(5):
            self.client.post(self.url, {"password": "incorrect"})

        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 429)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_promotion_limit_is_lifted_after_an_hour(self):
        for _ in range(5):
            self.client.post(self.url, {"password": "incorrect"})
        FailedAttempt.objects.update(
            attempted_at=timezone.now() - timedelta(hours=1, minutes=1)
        )

        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 200)

    def test_promotion_limit_is_counted_per_account(self):
        for _ in range(5):
            self.client.post(self.url, {"password": "incorrect"})
        other = get_user_model().objects.create_user(username="other-member")
        make_member(other)
        self.client.force_login(other)

        response = self.client.post(self.url, {"password": "incorrect"})

        self.assertEqual(response.status_code, 400)

    def test_promotion_password_is_for_club_members_only(self):
        outsider = get_user_model().objects.create_user(
            username="non-member", is_staff=True
        )
        self.client.force_login(outsider)

        response = self.client.post(self.url, {"password": "promotion-pass-123"})

        self.assertEqual(response.status_code, 403)
        outsider.refresh_from_db()
        self.assertFalse(outsider.is_superuser)

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
            is_member=True,
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

    def test_vapid_mismatch_requests_push_subscription_refresh(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/mismatch",
            p256dh="public-key",
            auth="auth-secret",
        )
        error = WebPushException("VAPID mismatch")
        error.response = SimpleNamespace(status_code=403)
        with patch("accounts.views.send_web_push", side_effect=error):
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

        self.assertEqual(response.status_code, 409)
        self.assertIn("再登録", response.json()["error"])
        subscription.refresh_from_db()
        self.assertFalse(subscription.news_notifications_enabled)

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


class AudienceTests(TestCase):
    """校外・部外・部内の判定(accounts.audience)。"""

    def setUp(self):
        user_model = get_user_model()
        self.non_member = user_model.objects.create_user(username="school-user")
        self.member = user_model.objects.create_user(username="club-user")
        make_member(self.member)

    def test_anonymous_visitor_is_outside_school(self):
        from django.contrib.auth.models import AnonymousUser

        visitor = AnonymousUser()

        self.assertEqual(audience_of(visitor), Audience.PUBLIC)
        self.assertTrue(is_outside_school(visitor))
        self.assertEqual(visible_audiences(visitor), [Audience.PUBLIC])

    def test_logged_in_user_without_membership_is_school_non_member(self):
        self.assertEqual(audience_of(self.non_member), Audience.SCHOOL)
        self.assertTrue(is_school_non_member(self.non_member))
        self.assertFalse(is_club_member(self.non_member))
        self.assertEqual(
            visible_audiences(self.non_member), [Audience.PUBLIC, Audience.SCHOOL]
        )

    def test_roster_entry_without_member_flag_is_not_a_member(self):
        user = get_user_model().objects.create_user(username="teacher")
        RosterEntry.objects.create(name="顧問でない先生", is_member=False, account=user)

        self.assertTrue(is_school_non_member(user))

    def test_linked_member_is_club_member(self):
        self.assertEqual(audience_of(self.member), Audience.CLUB)
        self.assertTrue(is_club_member(self.member))
        self.assertTrue(can_view(self.member, Audience.CLUB))

    def test_superuser_counts_as_club_member_and_editor(self):
        admin_user = get_user_model().objects.create_superuser(
            username="root", password="pw"
        )

        self.assertTrue(is_club_member(admin_user))
        self.assertTrue(is_club_editor(admin_user))

    def test_inactive_account_is_treated_as_outside_school(self):
        self.member.is_active = False

        self.assertTrue(is_outside_school(self.member))

    def test_only_superusers_are_editors(self):
        self.assertFalse(is_club_editor(self.member))

        staff_member = get_user_model().objects.create_user(
            username="staff-member", is_staff=True
        )
        make_member(staff_member)
        self.assertFalse(is_club_editor(staff_member))

        admin_user = get_user_model().objects.create_superuser(
            username="editor", password="pw"
        )
        self.assertTrue(is_club_editor(admin_user))


class ClubOnlyAccessTests(TestCase):
    """部外の人(ログイン済みの非部員)は、ニュース以外の部内ページに入れないこと。"""

    MEMBER_URL_NAMES = [
        "equipment:dashboard",
        "equipment:list",
        "equipment:register",
        "equipment:lending",
        "equipment:locations",
        "equipment:settings",
        "manuals:manual_list",
        "video_archive:video_list",
        "schedule:calendar",
        "schedule:week",
        "places_api:list",
    ]
    EDITOR_URL_NAMES = [
        "roll:list",
        "roll:import_csv",
        "places:list",
        "places:create",
        "manuals:manual_create",
        "schedule:event_create",
        "main:news_create",
    ]

    def setUp(self):
        user_model = get_user_model()
        # 以前は「学校のGoogleアカウントなら全員スタッフ」だったので、
        # スタッフ権限つきの非部員でも入れないことを確かめる
        self.non_member = user_model.objects.create_user(
            username="school-user", is_staff=True
        )
        # スタッフ権限つきの部員も、編集はできない(編集はスーパーユーザーだけ)
        self.member = user_model.objects.create_user(
            username="club-user", is_staff=True
        )
        make_member(self.member)
        self.editor = user_model.objects.create_superuser(
            username="club-editor", password="pw"
        )

    def test_non_member_is_refused_everywhere_but_news(self):
        self.client.force_login(self.non_member)

        for name in self.MEMBER_URL_NAMES + self.EDITOR_URL_NAMES:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

        self.assertEqual(self.client.get(reverse("main:news_all")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:mypage")).status_code, 200)

    def test_non_member_does_not_see_roster_names(self):
        RosterEntry.objects.create(name="名簿の生徒", grade="2", homeroom="3")
        self.client.force_login(self.non_member)

        for name in ("equipment:list", "equipment:register", "equipment:lending_register"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 403)
                self.assertNotContains(response, "名簿の生徒", status_code=403)

    def test_non_member_cannot_upload_images(self):
        self.client.force_login(self.non_member)

        response = self.client.post(reverse("ck_editor_5_upload_file"))

        self.assertEqual(response.status_code, 403)

    def test_member_can_view_but_not_manage(self):
        self.client.force_login(self.member)

        for name in self.MEMBER_URL_NAMES:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for name in self.EDITOR_URL_NAMES:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_editor_can_manage(self):
        self.client.force_login(self.editor)

        for name in self.MEMBER_URL_NAMES + self.EDITOR_URL_NAMES:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_anonymous_visitor_is_sent_to_login(self):
        for name in self.MEMBER_URL_NAMES + self.EDITOR_URL_NAMES:
            if name == "places_api:list":
                continue  # APIはリダイレクトではなく401を返す
            with self.subTest(url=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertEqual(self.client.get(reverse("places_api:list")).status_code, 401)

    def test_apps_on_homepage_are_listed_for_members_only(self):
        equipment_url = reverse("equipment:dashboard")

        self.assertNotContains(self.client.get(reverse("main:index")), equipment_url)

        self.client.force_login(self.non_member)
        self.assertNotContains(self.client.get(reverse("main:index")), equipment_url)

        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("main:index")), equipment_url)


class ClosedSignupTests(TestCase):
    def test_signup_page_does_not_offer_a_form(self):
        response = self.client.get("/accounts/signup/")

        self.assertNotContains(response, 'name="password1"')

    def test_posting_to_signup_does_not_create_an_account(self):
        self.client.post(
            "/accounts/signup/",
            {
                "username": "outsider",
                "password1": "Zx-outsider-9981",
                "password2": "Zx-outsider-9981",
            },
        )

        self.assertFalse(get_user_model().objects.filter(username="outsider").exists())
        response = self.client.get(reverse("accounts:mypage"))
        self.assertEqual(response.status_code, 302)

    def test_password_signup_adapter_is_closed(self):
        adapter = ClosedSignupAccountAdapter()

        self.assertFalse(adapter.is_open_for_signup(RequestFactory().get("/")))

    def test_google_signup_is_closed(self):
        adapter = RakunanSocialAccountAdapter()

        self.assertFalse(adapter.is_open_for_signup(RequestFactory().get("/"), None))
        existing_sociallogin = SimpleNamespace(is_existing=True)
        self.assertTrue(
            adapter.is_open_for_signup(
                RequestFactory().get("/"),
                existing_sociallogin,
            )
        )


class LoginThrottleTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:login")
        self.user = get_user_model().objects.create_user(
            username="member", password="Member-pass-123"
        )

    def fail(self, username="member", times=5):
        for _ in range(times):
            response = self.client.post(
                self.url, {"username": username, "password": "wrong"}
            )
            self.assertEqual(response.status_code, 200)

    def test_sixth_attempt_is_refused_even_with_the_right_password(self):
        self.fail()

        response = self.client.post(
            self.url, {"username": "member", "password": "Member-pass-123"}
        )

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "一時的に受け付けを止めています", status_code=429)
        self.assertEqual(self.client.get(reverse("accounts:mypage")).status_code, 302)

    def test_limit_cannot_be_dodged_by_changing_letter_case_or_session(self):
        self.fail()
        self.client.cookies.clear()

        response = self.client.post(
            self.url, {"username": "MEMBER ", "password": "Member-pass-123"}
        )

        self.assertEqual(response.status_code, 429)

    def test_other_accounts_are_not_affected(self):
        get_user_model().objects.create_user(
            username="another", password="Another-pass-123"
        )
        self.fail()

        response = self.client.post(
            self.url, {"username": "another", "password": "Another-pass-123"}
        )

        self.assertRedirects(response, reverse("accounts:mypage"))

    def test_successful_login_resets_the_count(self):
        self.fail(times=4)
        self.client.post(self.url, {"username": "member", "password": "Member-pass-123"})
        self.client.get(reverse("accounts:logout"))

        self.fail(times=4)
        response = self.client.post(
            self.url, {"username": "member", "password": "Member-pass-123"}
        )

        self.assertRedirects(response, reverse("accounts:mypage"))

    def test_limit_is_lifted_after_an_hour(self):
        self.fail()
        FailedAttempt.objects.update(
            attempted_at=timezone.now() - timedelta(hours=1, minutes=1)
        )

        response = self.client.post(
            self.url, {"username": "member", "password": "Member-pass-123"}
        )

        self.assertRedirects(response, reverse("accounts:mypage"))

    def test_old_records_are_cleaned_up(self):
        self.fail(username="someone-else", times=3)
        FailedAttempt.objects.update(
            attempted_at=timezone.now() - timedelta(hours=2)
        )

        self.fail(times=1)

        self.assertEqual(FailedAttempt.objects.count(), 1)


class AdminLoginTests(TestCase):
    """管理画面には専用のログインフォームがなく、サイトのログイン(回数制限つき)を通ること。"""

    def test_anonymous_visitor_is_sent_to_site_login(self):
        response = self.client.get("/admin/login/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_admin_login_does_not_accept_passwords(self):
        get_user_model().objects.create_superuser(username="root", password="Root-pass-123")

        response = self.client.post(
            "/admin/login/", {"username": "root", "password": "Root-pass-123"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_non_staff_user_is_refused(self):
        self.client.force_login(get_user_model().objects.create_user(username="plain"))

        self.assertEqual(self.client.get("/admin/login/").status_code, 403)

    def test_staff_user_goes_to_admin_index(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(username="root", password="pw")
        )

        self.assertRedirects(self.client.get("/admin/login/"), "/admin/")


@override_settings(
    SOCIALACCOUNT_PROVIDERS={
        "google": {"APP": {"client_id": "dummy", "secret": "dummy", "key": ""}}
    }
)
class GoogleLoginStaffTests(TestCase):
    """Googleでログインしても、スタッフ権限は自動では付かないこと。"""

    def google_login(self, email, uid):
        from allauth.core import context as allauth_context
        from allauth.socialaccount.adapter import get_adapter
        from allauth.socialaccount.helpers import complete_social_login
        from allauth.socialaccount.models import SocialAccount, SocialLogin
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get("/accounts/google/login/callback/")
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        request.user = AnonymousUser()
        with allauth_context.request_context(request):
            provider = get_adapter().get_provider(request, "google")
            sociallogin = SocialLogin(
                user=get_user_model()(email=email),
                account=SocialAccount(
                    provider="google", uid=uid, extra_data={"email": email}
                ),
                provider=provider,
            )
            sociallogin.state = {}
            return complete_social_login(request, sociallogin)

    def test_new_school_account_is_not_created(self):
        self.google_login("newbie@rakunan-h.ed.jp", "uid-1")

        self.assertFalse(
            get_user_model().objects.filter(email="newbie@rakunan-h.ed.jp").exists()
        )

    def test_non_school_account_is_refused(self):
        self.google_login("someone@gmail.com", "uid-2")

        self.assertFalse(get_user_model().objects.filter(email="someone@gmail.com").exists())

    def test_returning_user_is_not_promoted_to_staff(self):
        user = get_user_model().objects.create_user(
            username="again",
            email="again@rakunan-h.ed.jp",
        )
        SocialAccount.objects.create(
            user=user,
            provider="google",
            uid="uid-3",
        )
        self.google_login("again@rakunan-h.ed.jp", "uid-3")

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
