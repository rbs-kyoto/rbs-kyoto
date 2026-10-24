from datetime import date, timedelta
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import checks
from .models import Level, SystemStatus

TODAY = date(2026, 10, 24)


def fake_response(payload, status=200):
    response = mock.Mock()
    response.status_code = status
    response.json.return_value = payload
    response.raise_for_status.side_effect = None if status == 200 else requests.HTTPError(status)
    return response


def rdap(expires_on):
    return {"events": [{"eventAction": "registration", "eventDate": "2026-08-19T15:37:33Z"},
                       {"eventAction": "expiration", "eventDate": f"{expires_on}T15:37:33.111Z"}]}


class DomainCheckTests(TestCase):
    def check(self, payload):
        with mock.patch("system_status.checks.requests.get", return_value=fake_response(payload)) as get:
            item = checks.check_domain("rbs-kyoto.org", TODAY)
        get.assert_called_once_with("https://rdap.org/domain/rbs-kyoto.org", timeout=checks.TIMEOUT)
        return item

    def test_levels_follow_days_left(self):
        cases = [(300, Level.OK), (90, Level.WARNING), (30, Level.DANGER), (-1, Level.DANGER)]
        for days, level in cases:
            with self.subTest(days=days):
                item = self.check(rdap(TODAY + timedelta(days=days)))
                self.assertEqual(item["level"], level)

    def test_value_shows_date_and_days_left(self):
        item = self.check(rdap(date(2027, 8, 19)))
        self.assertEqual(item["value"], "2027年8月19日（あと299日）")

    def test_expired_domain_says_so(self):
        item = self.check(rdap(TODAY - timedelta(days=3)))
        self.assertIn("期限切れ", item["value"])
        self.assertIn("更新手続き", item["advice"])

    def test_network_or_format_problems_are_unknown_not_alarming(self):
        for side_effect in (requests.ConnectionError(), None):
            with self.subTest(side_effect=side_effect):
                response = fake_response({"events": []})
                with mock.patch("system_status.checks.requests.get", side_effect=side_effect, return_value=response):
                    item = checks.check_domain("rbs-kyoto.org", TODAY)
                self.assertEqual(item["level"], Level.UNKNOWN)


class SoftwareCheckTests(TestCase):
    def check(self, key, payload, installed="6.1"):
        with mock.patch("system_status.checks.requests.get", return_value=fake_response(payload)):
            return checks.check_software(key, "Django", "django", "6.1", installed, today=TODAY)

    def test_supported_version_is_ok(self):
        item = self.check("django", {"eol": "2027-12-31", "latest": "6.1"})
        self.assertEqual(item["level"], Level.OK)
        self.assertIn("2027年12月31日", item["detail"])

    def test_support_ending_soon_is_a_warning(self):
        item = self.check("django", {"eol": str(TODAY + timedelta(days=100)), "latest": "6.1"})
        self.assertEqual(item["level"], Level.WARNING)

    def test_ended_support_needs_action(self):
        for eol in (str(TODAY - timedelta(days=1)), True):
            with self.subTest(eol=eol):
                item = self.check("django", {"eol": eol, "latest": "6.1"})
                self.assertEqual(item["level"], Level.DANGER)
                self.assertIn("相談", item["advice"])

    def test_newer_django_patch_is_reported(self):
        item = self.check("django", {"eol": "2027-12-31", "latest": "6.1.2"})
        self.assertEqual(item["level"], Level.INFO)
        self.assertIn("6.1.2", item["detail"])

    def test_distro_packages_are_not_compared_by_patch_number(self):
        item = self.check("php", {"eol": "2027-12-31", "latest": "8.3.36"}, installed="8.3.6")
        self.assertEqual(item["level"], Level.OK)

    def test_unknown_eol_date_is_ok(self):
        item = self.check("django", {"eol": False, "latest": "6.1"})
        self.assertEqual(item["level"], Level.OK)


class DiskCheckTests(TestCase):
    def test_levels_follow_free_space(self):
        for free, level in ((50, Level.OK), (15, Level.WARNING), (5, Level.DANGER)):
            with self.subTest(free=free):
                usage = mock.Mock(total=100 * 1024 ** 3, free=free * 1024 ** 3)
                with mock.patch("system_status.checks.shutil.disk_usage", return_value=usage):
                    self.assertEqual(checks.check_disk("/")["level"], level)


@override_settings(ROOT_URLCONF="config.urls_admin", SITE_ROLE="admin")
class StatusPageTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass")
        self.staff = get_user_model().objects.create_user("staff", "staff@example.com", "pass", is_staff=True)
        self.results = [checks.result("domain", "ドメイン", "2026年11月1日（あと8日）", Level.DANGER, "", "更新してください。")]

    def test_page_runs_checks_when_results_are_stale(self):
        self.client.force_login(self.staff)
        with mock.patch("system_status.checks.run_all", return_value=self.results) as run_all:
            response = self.client.get(reverse("system_status:status"))

        run_all.assert_called_once()
        self.assertContains(response, "すぐに対応が必要な項目があります。")
        self.assertContains(response, "更新してください。")

    def test_fresh_results_are_not_checked_again(self):
        SystemStatus.objects.create(pk=1, results=self.results, checked_at=timezone.now())
        self.client.force_login(self.staff)
        with mock.patch("system_status.checks.run_all") as run_all:
            self.client.get(reverse("system_status:status"))
        run_all.assert_not_called()

    def test_check_now_button(self):
        SystemStatus.objects.create(pk=1, results=[], checked_at=timezone.now())
        self.client.force_login(self.staff)
        with mock.patch("system_status.checks.run_all", return_value=self.results) as run_all:
            self.client.post(reverse("system_status:check_now"))
        run_all.assert_called_once()
        self.assertEqual(SystemStatus.get_solo().results[0]["key"], "domain")

    def test_only_superusers_can_edit_notes(self):
        SystemStatus.objects.create(pk=1, checked_at=timezone.now())
        url = reverse("system_status:update_notes")

        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, {"notes": "x"}).status_code, 403)

        self.client.force_login(self.superuser)
        self.client.post(url, {"notes": "顧問：〇〇先生"})
        self.assertEqual(SystemStatus.get_solo().notes, "顧問：〇〇先生")

    def test_header_and_sidebar_flag_problems_on_every_admin_page(self):
        SystemStatus.objects.create(pk=1, results=self.results, checked_at=timezone.now())
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:main_news_changelist"))

        self.assertContains(response, "要対応あり")
        self.assertContains(response, reverse("system_status:status"))
