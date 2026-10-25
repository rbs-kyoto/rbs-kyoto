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


import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from opsd import protocol
from opsd.maintenance import Schedule

from .models import MaintenanceSetting
from .signals import schedule_params


class OperatorHandoffTests(TestCase):
    def setUp(self):
        self.spool = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.spool, ignore_errors=True)
        (self.spool / "requests").mkdir()

    def written(self):
        return [json.loads(path.read_text()) for path in (self.spool / "requests").glob("*.json")]

    def test_saving_the_setting_hands_the_schedule_to_the_operator(self):
        starts = timezone.now() + timedelta(days=1)
        with override_settings(OPS_SPOOL=self.spool):
            setting = MaintenanceSetting.get_solo()
            setting.mode = MaintenanceSetting.Mode.PLANNED
            setting.starts_at = starts
            setting.auto_resume_at = starts + timedelta(hours=2)
            setting.announcement = "夜間に作業します"
            setting.save()

        [request] = self.written()
        self.assertEqual(request["action"], "maintenance_set")
        self.assertEqual(request["source"], "django:maintenance")
        params = request["params"]
        self.assertEqual((params["mode"], params["announcement"]), ("planned", "夜間に作業します"))
        self.assertEqual(protocol.validate("maintenance_set", params), params)
        self.assertEqual(Schedule.from_params(params).status_at(timezone.now()), "inactive")

    def test_nothing_happens_without_an_operator(self):
        with override_settings(OPS_SPOOL=None):
            setting = MaintenanceSetting.get_solo()
            setting.save()
        self.assertEqual(self.written(), [])

    def test_a_missing_spool_directory_does_not_break_saving(self):
        with override_settings(OPS_SPOOL=self.spool / "nope"):
            MaintenanceSetting.get_solo().save()

    def test_very_long_announcements_are_cut_instead_of_rejected(self):
        with override_settings(OPS_SPOOL=self.spool):
            setting = MaintenanceSetting.get_solo()
            setting.announcement = "あ" * 5000
            setting.save()
        [request] = self.written()
        self.assertEqual(len(request["params"]["announcement"]), protocol.MAX_ANNOUNCEMENT_LENGTH)


class ScheduleParityTests(TestCase):
    """opsd の予定の判定は、Django のモデルの判定と、まったく同じ結果になること。"""

    def test_every_case_agrees_with_the_django_model(self):
        base = timezone.now().replace(microsecond=0)
        hour = timedelta(hours=1)
        times = {"none": None, "past": base - 2 * hour, "soon": base + hour, "later": base + 3 * hour}
        cases = 0
        for mode in MaintenanceSetting.Mode.values:
            for start_name, starts in times.items():
                for resume_name, resume in times.items():
                    for recovery in (False, True):
                        with self.subTest(mode=mode, start=start_name, auto_resume=resume_name, recovery=recovery):
                            setting = MaintenanceSetting(mode=mode, starts_at=starts, auto_resume_at=resume, recovery_in_progress=recovery)
                            schedule = Schedule.from_params(schedule_params(setting))
                            for offset in (-4, 0, 2, 4, 5):
                                moment = base + offset * hour
                                self.assertEqual(schedule.status_at(moment), setting.status_at(moment).value, offset)
                            cases += 1
        self.assertEqual(cases, 3 * 4 * 4 * 2)
