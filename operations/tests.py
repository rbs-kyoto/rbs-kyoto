import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from opsd import protocol


@override_settings(ROOT_URLCONF="config.urls_admin", SITE_ROLE="admin")
class OperationsViewTests(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.spool = self.root / "spool"
        for name in ("requests", "results"):
            (self.spool / name).mkdir(parents=True)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        settings_override = override_settings(OPS_SPOOL=self.spool, OPS_BACKUPS=self.backups)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        User = get_user_model()
        self.superuser = User.objects.create_superuser("root", "root@example.com", "pass")
        self.staff = User.objects.create_user("staff", "staff@example.com", "pass", is_staff=True)
        self.client.force_login(self.superuser)

    def run_action(self, action, params=None, **extra):
        return self.client.post(
            reverse("operations:run"),
            json.dumps({"action": action, "params": params or {}}),
            content_type="application/json",
            **extra,
        )

    def written(self):
        return [json.loads(path.read_text()) for path in (self.spool / "requests").glob("*.json")]

    def test_page_lists_actions_and_recent_results(self):
        request_id = protocol.new_request_id()
        (self.spool / "results" / f"{request_id}.json").write_text(
            json.dumps({"id": request_id, "action": "backup", "status": "succeeded", "requested_at": "2026-10-25T05:00:00", "source": "rescue"})
        )

        response = self.client.get(reverse("operations:index"))

        self.assertContains(response, "管理画面（Django）のソースを取り直す")
        self.assertContains(response, "救出画面")
        self.assertContains(response, "2026-10-25 05:00")
        self.assertContains(response, "成功")

    def test_page_explains_when_there_is_no_operator(self):
        with override_settings(OPS_SPOOL=None):
            response = self.client.get(reverse("operations:index"))
            self.assertContains(response, "この環境では使えません")
            self.assertEqual(self.run_action("backup").status_code, 503)

    def test_only_superusers_can_use_it(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("operations:index")).status_code, 403)
        self.assertEqual(self.run_action("backup").status_code, 403)
        self.assertEqual(self.client.get(reverse("operations:status", args=["20261025040000-aaaaaaaa"])).status_code, 403)
        self.assertEqual(self.written(), [])

        self.client.logout()
        self.assertEqual(self.run_action("backup").status_code, 302)

    def test_run_writes_a_request_with_who_asked(self):
        response = self.run_action("restart", {"service": "web"})

        self.assertEqual(response.status_code, 200)
        [request] = self.written()
        self.assertEqual(request["id"], response.json()["id"])
        self.assertEqual(request["action"], "restart")
        self.assertEqual(request["params"], {"service": "web"})
        self.assertEqual(request["source"], "django:root")

    def test_restore_and_rollback_are_not_available_from_django(self):
        for action, params in (("restore", {"backup": "20261025-040000-manual"}), ("rollback", {})):
            with self.subTest(action=action):
                response = self.run_action(action, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("救出画面", response.json()["error"])
        self.assertEqual(self.written(), [])

    def test_bad_requests_are_rejected_without_writing(self):
        cases = [
            ("restart", {"service": "opsd"}),
            ("logs", {"service": "admin", "lines": 99999}),
            ("rm -rf", {}),
        ]
        for action, params in cases:
            with self.subTest(action=action, params=params):
                self.assertEqual(self.run_action(action, params).status_code, 400)
        response = self.client.post(reverse("operations:run"), "not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.written(), [])

    def test_run_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse("operations:run")).status_code, 405)
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.superuser)
        response = csrf_client.post(reverse("operations:run"), json.dumps({"action": "backup"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.written(), [])

    def test_status_follows_a_request_from_queued_to_finished(self):
        request_id = self.run_action("backup").json()["id"]
        url = reverse("operations:status", args=[request_id])

        self.assertEqual(self.client.get(url).json()["status"], protocol.QUEUED)

        (self.spool / "results" / f"{request_id}.json").write_text(
            json.dumps({"id": request_id, "action": "backup", "status": "succeeded", "output": "done"})
        )
        done = self.client.get(url)
        self.assertEqual(done.json()["status"], protocol.SUCCEEDED)
        self.assertEqual(done["Cache-Control"], "no-store")

    def test_status_for_unknown_or_malformed_ids_is_404(self):
        self.assertEqual(self.client.get(reverse("operations:status", args=["20261025040000-aaaaaaaa"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("operations:status", args=["..%2F..%2Fetc"])).status_code, 404)

    def test_maintenance_card_shows_the_operators_state(self):
        (self.spool / "maintenance.json").write_text(json.dumps({
            "configured": True, "last_error": "権限が足りません",
            "applied": {"enabled": True, "message": "整理中", "at": "2026-10-26T01:00:00"},
            "schedule": {"mode": "planned", "starts_at": "2026-10-26T01:00:00+09:00", "auto_resume_at": "2026-10-26T03:00:00+09:00"},
        }))
        response = self.client.get(reverse("operations:index"))
        self.assertContains(response, "メンテナンス中")
        self.assertContains(response, "「整理中」")
        self.assertContains(response, "権限が足りません")
        self.assertContains(response, "2026-10-26 01:00")

        (self.spool / "maintenance.json").write_text(json.dumps({"configured": False}))
        self.assertContains(self.client.get(reverse("operations:index")), "Cloudflare が未設定です")
        (self.spool / "maintenance.json").unlink()
        self.assertContains(self.client.get(reverse("operations:index")), "まだ状態がありません")

    def test_maintenance_can_be_started_and_ended_from_django(self):
        started = self.run_action("maintenance_on", {"message": "整理中"})
        ended = self.run_action("maintenance_off")
        self.assertEqual((started.status_code, ended.status_code), (200, 200))
        self.assertCountEqual([item["action"] for item in self.written()], ["maintenance_on", "maintenance_off"])
        self.assertEqual(self.run_action("maintenance_on", {"message": "あ" * 201}).status_code, 400)

    def test_autoupdate_card_shows_state_and_toggles_from_django(self):
        self.assertContains(self.client.get(reverse("operations:index")), "自動更新")
        (self.spool / "autoupdate.json").write_text(json.dumps({"enabled": False, "last_slot": "2026-10-25T04:00"}))
        self.assertContains(self.client.get(reverse("operations:index")), "オンにする")

        self.assertEqual(self.run_action("autoupdate_set", {"enabled": True}).status_code, 200)
        self.assertEqual(self.run_action("autoupdate_set", {"enabled": "yes"}).status_code, 400)
        [request] = self.written()
        self.assertEqual(request["params"], {"enabled": True})

    def test_sidebar_links_to_the_page(self):
        response = self.client.get(reverse("operations:index"))
        self.assertContains(response, 'href="/ops/"')
        self.assertContains(response, "システムの操作")


class HealthzTests(TestCase):
    def test_healthz_reports_ok_when_the_db_is_readable(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_healthz_is_reachable_during_maintenance(self):
        from maintenance.models import MaintenanceSetting

        setting = MaintenanceSetting.get_solo()
        setting.mode = MaintenanceSetting.Mode.EMERGENCY
        setting.save()
        self.assertEqual(self.client.get("/healthz/").status_code, 200)
