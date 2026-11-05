import json

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from equipment.models import Category, Equipment, ReturnRecord, UsageRecord
from roll.models import RosterEntry
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
