from datetime import datetime, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .middleware import MaintenanceModeMiddleware
from .models import MaintenanceSetting


class MaintenanceSettingTests(TestCase):
    def setUp(self):
        self.setting = MaintenanceSetting.get_solo()
        self.start = datetime(2026, 10, 20, 12, tzinfo=datetime_timezone.utc)
        self.resume = datetime(2026, 10, 20, 13, tzinfo=datetime_timezone.utc)

    def test_planned_maintenance_starts_and_resumes_automatically(self):
        self.setting.mode = MaintenanceSetting.Mode.PLANNED
        self.setting.starts_at = self.start
        self.setting.resume_at = self.resume
        self.setting.auto_resume_at = self.resume
        self.setting.save()

        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 11, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.INACTIVE,
        )
        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 12, 30, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.ACTIVE,
        )
        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 13, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.INACTIVE,
        )

    def test_planned_maintenance_stays_active_for_overdue_recovery(self):
        self.setting.mode = MaintenanceSetting.Mode.PLANNED
        self.setting.starts_at = self.start
        self.setting.resume_at = self.resume
        self.setting.auto_resume_at = self.resume
        self.setting.recovery_in_progress = True
        self.setting.save()

        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 13, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.RECOVERY,
        )

    def test_announcement_time_does_not_resume_without_auto_resume_schedule(self):
        self.setting.mode = MaintenanceSetting.Mode.PLANNED
        self.setting.starts_at = self.start
        self.setting.resume_at = self.resume
        self.setting.save()

        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 14, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.ACTIVE,
        )

    def test_emergency_maintenance_requires_manual_deactivation(self):
        self.setting.mode = MaintenanceSetting.Mode.EMERGENCY
        self.setting.resume_at = self.resume
        self.setting.save()

        self.assertEqual(
            self.setting.status_at(datetime(2026, 10, 20, 14, tzinfo=datetime_timezone.utc)),
            MaintenanceSetting.Status.ACTIVE,
        )

    def test_maintenance_page_is_served_with_503_during_emergency(self):
        self.setting.mode = MaintenanceSetting.Mode.EMERGENCY
        self.setting.resume_at = self.resume
        self.setting.announcement = "緊急メンテナンスを実施しています。"
        self.setting.save()
        now = datetime(2026, 10, 20, 12, tzinfo=datetime_timezone.utc)
        request = RequestFactory().get("/videos/")
        middleware = MaintenanceModeMiddleware(lambda request: None)

        from unittest.mock import patch

        with patch("maintenance.middleware.timezone.now", return_value=now):
            response = middleware(request)

        self.assertEqual(response.status_code, 503)
        self.assertIn(
            "緊急メンテナンスを実施しています。",
            response.content.decode(),
        )
        content = response.content.decode()
        self.assertIn("サービス再開予定", content)
        self.assertIn("2026年10月20日", content)
        self.assertIn('class="logo"', content)
        self.assertIn("main/css/error.css", content)
        self.assertIn('class="error-heading"', content)

    def test_admin_url_bypasses_maintenance_but_requires_django_admin_auth(self):
        self.setting.mode = MaintenanceSetting.Mode.EMERGENCY
        self.setting.save()
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)

    def test_maintenance_controls_are_superuser_only(self):
        staff_user = get_user_model().objects.create_user(
            username="staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff_user)
        response = self.client.get(
            reverse("admin:maintenance_maintenancesetting_changelist")
        )

        self.assertEqual(response.status_code, 403)

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)
        response = self.client.get(
            reverse("admin:maintenance_maintenancesetting_changelist")
        )

        self.assertEqual(response.status_code, 200)
