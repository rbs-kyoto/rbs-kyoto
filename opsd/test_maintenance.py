import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import cloudflare, maintenance, protocol
from .daemon import Config, Job, Ops, OpsError
from .fake_cloudflare import FakeCloudflare
from .maintenance import ACTIVE, INACTIVE, RECOVERY, Schedule

TOKEN = "good-token"
JST = timezone(timedelta(hours=9))


def at(hour, minute=0, day=26):
    return datetime(2026, 10, day, hour, minute, tzinfo=JST)


class ScheduleTests(unittest.TestCase):
    def test_off_is_always_inactive(self):
        self.assertEqual(Schedule(mode="off", announcement="x").status_at(at(12)), INACTIVE)

    def test_emergency_is_active_until_turned_off_and_can_be_recovery(self):
        self.assertEqual(Schedule(mode="emergency").status_at(at(12)), ACTIVE)
        self.assertEqual(Schedule(mode="emergency", recovery_in_progress=True).status_at(at(12)), RECOVERY)

    def test_planned_window(self):
        plan = Schedule(mode="planned", starts_at=at(1).isoformat(), auto_resume_at=at(3).isoformat())
        self.assertEqual(plan.status_at(at(0, 59)), INACTIVE)
        self.assertEqual(plan.status_at(at(1)), ACTIVE)
        self.assertEqual(plan.status_at(at(2, 59)), ACTIVE)
        self.assertEqual(plan.status_at(at(3)), INACTIVE)

    def test_planned_can_continue_as_recovery_after_the_auto_resume_time(self):
        plan = Schedule(mode="planned", starts_at=at(1).isoformat(), auto_resume_at=at(3).isoformat(), recovery_in_progress=True)
        self.assertEqual(plan.status_at(at(4)), RECOVERY)

    def test_planned_without_a_start_time_never_starts(self):
        self.assertEqual(Schedule(mode="planned").status_at(at(12)), INACTIVE)

    def test_times_without_an_offset_mean_this_machines_local_time(self):
        plan = Schedule(mode="planned", starts_at="2026-10-26T01:00:00")
        local = datetime(2026, 10, 26, 1, 0, 0).astimezone()
        self.assertEqual(plan.status_at(local), ACTIVE)
        self.assertEqual(plan.status_at(local - timedelta(minutes=1)), INACTIVE)
        self.assertEqual(plan.status_at(local.replace(tzinfo=None)), ACTIVE)

    def test_wanted_collapses_the_message_and_shows_the_resume_time(self):
        plan = Schedule(mode="emergency", announcement="データベースの\n  更新中です", resume_at="2026-10-26T10:00:00+09:00")
        self.assertEqual(plan.wanted(at(12)), (True, "データベースの 更新中です", "2026-10-26 10:00"))
        self.assertEqual(Schedule(mode="off").wanted(at(12)), (False, "", ""))

    def test_recovery_gets_a_default_message(self):
        self.assertEqual(Schedule(mode="emergency", recovery_in_progress=True).wanted(at(12))[1], maintenance.RECOVERY_NOTICE)


class MaintenanceOpsTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.fake = FakeCloudflare(token=TOKEN, rules=[
            {"id": "other", "ref": "someone-elses", "action": "redirect", "enabled": True, "expression": "(http.host eq \"x\")",
             "action_parameters": {"from_value": {"target_url": {"value": "https://example.com"}, "status_code": 301}}},
            {"id": "rule9", "ref": cloudflare.RULE_REF, "action": "redirect", "enabled": False, "expression": "false",
             "action_parameters": {}},
        ]).start()
        self.addCleanup(self.fake.stop)
        self.clock = [datetime(2026, 10, 26, 0, 0, 0)]
        self.ops = Ops(Config(home=self.home), runner=lambda *a, **k: (0, ""), now=lambda: self.clock[0])
        self.ops.recover()
        self.configure()

    def configure(self, **overrides):
        values = {
            "CF_API_TOKEN": TOKEN, "CF_ZONE_ID": "zone1", "CF_RULESET_ID": "ruleset1", "CF_RULE_ID": "rule9",
            "CF_PUBLIC_HOSTS": "poc-rbs.clusters-prj.com", "MAINTENANCE_URL": "https://rbs-maintenance.sub.workers.dev/",
            "CF_API_BASE": self.fake.base, **overrides,
        }
        (self.home / "cloudflare.env").write_text("\n".join(f"{k}={v}" for k, v in values.items()))

    def job(self, action, params=None):
        return Job(self.ops, {"id": protocol.new_request_id(self.clock[0]), "action": action, "params": params or {}, "source": "test"})

    def run_action(self, action, params=None):
        job = self.job(action, params)
        self.ops.execute(job, action, protocol.validate(action, params))
        return job

    def tick(self, minutes=0, seconds=0):
        self.clock[0] += timedelta(minutes=minutes, seconds=seconds)
        self.ops.maintenance_tick()

    def patches(self):
        return [body for _, _, body in self.fake.calls("PATCH")]

    def state(self):
        return json.loads((self.home / "spool" / "maintenance.json").read_text())

    def target_query(self, patch):
        expression = patch["action_parameters"]["from_value"]["target_url"]["expression"]
        url = expression.removeprefix('concat("').removesuffix('", http.host)')
        return parse_qs(urlparse(url).query)

    # --- 手動の切り替え ---------------------------------------------------

    def test_turning_it_on_enables_only_our_rule_with_every_field(self):
        job = self.run_action("maintenance_on", {"message": "データベースを更新中です"})

        [patch] = self.patches()
        self.assertTrue(patch["enabled"])
        self.assertEqual(patch["ref"], cloudflare.RULE_REF)
        self.assertEqual(patch["action"], "redirect")
        self.assertEqual(patch["expression"], '(http.host in {"poc-rbs.clusters-prj.com"})')
        self.assertEqual(patch["action_parameters"]["from_value"]["status_code"], 302)
        self.assertEqual(self.target_query(patch)["msg"], ["データベースを更新中です"])
        self.assertIn("メンテナンスを始めました", "\n".join(job.lines))
        self.assertTrue(self.state()["applied"]["enabled"])

    def test_it_never_replaces_the_whole_ruleset_and_leaves_other_rules_alone(self):
        self.run_action("maintenance_on", {"message": ""})
        self.run_action("maintenance_off")

        self.assertFalse(self.fake.put_called)
        self.assertEqual(self.fake.calls("POST"), [])
        other = next(rule for rule in self.fake.ruleset["rules"] if rule["id"] == "other")
        self.assertTrue(other["enabled"])
        self.assertEqual(other["action_parameters"]["from_value"]["target_url"], {"value": "https://example.com"})

    def test_turning_it_off_disables_the_rule(self):
        self.run_action("maintenance_on", {"message": "x"})
        job = self.run_action("maintenance_off")

        self.assertFalse(self.patches()[-1]["enabled"])
        self.assertIn("メンテナンスを終えました", "\n".join(job.lines))
        self.assertFalse(self.state()["applied"]["enabled"])

    def test_on_and_off_always_reassert_the_state_even_if_it_looks_unchanged(self):
        self.run_action("maintenance_on", {"message": "x"})
        self.run_action("maintenance_on", {"message": "x"})
        self.assertEqual(len(self.patches()), 2)

    def test_message_with_quotes_or_markup_cannot_break_out_of_the_expression(self):
        self.run_action("maintenance_on", {"message": 'a" or true; <script>alert(1)</script> \\'})
        [patch] = self.patches()
        expression = patch["action_parameters"]["from_value"]["target_url"]["expression"]
        self.assertEqual(expression.count('"'), 2)
        self.assertNotIn("<", expression)
        self.assertNotIn("\\", expression)
        self.assertEqual(self.target_query(patch)["msg"], ['a" or true; <script>alert(1)</script> \\'])

    def test_a_long_message_is_cut_for_the_url(self):
        self.run_action("maintenance_on", {"message": "あ" * 200})
        self.assertEqual(len(self.target_query(self.patches()[0])["msg"][0]), cloudflare.MAX_QUERY_TEXT)

    # --- 予定 ---------------------------------------------------------------

    def planned(self, **overrides):
        params = {"mode": "planned", "starts_at": "2026-10-26T01:00:00+09:00", "resume_at": "2026-10-26T04:00:00+09:00",
                  "auto_resume_at": "2026-10-26T03:00:00+09:00", "announcement": "夜間メンテナンス"}
        return {**params, **overrides}

    def test_a_planned_window_starts_and_ends_by_itself_without_django(self):
        # 時計は日本時間の 00:00 相当（このPCのローカル時刻）にする
        local = lambda h, m=0: datetime(2026, 10, 26, h, m)
        self.clock[0] = local(0)
        self.ops.config  # opsd だけが動いている想定（Django には依存しない）
        self.run_action("maintenance_set", self.planned(starts_at=local(1).isoformat(), auto_resume_at=local(3).isoformat(), resume_at=local(4).isoformat()))
        self.assertEqual([p["enabled"] for p in self.patches()], [False])  # 初回は「通常」を反映

        self.clock[0] = local(0, 59); self.ops.maintenance_tick()
        self.assertEqual(len(self.patches()), 1)

        self.clock[0] = local(1, 0); self.ops.maintenance_tick()
        self.assertEqual([p["enabled"] for p in self.patches()], [False, True])
        query = self.target_query(self.patches()[-1])
        self.assertEqual((query["msg"], query["until"]), (["夜間メンテナンス"], ["2026-10-26 04:00"]))

        self.clock[0] = local(2, 0); self.ops.maintenance_tick()
        self.assertEqual(len(self.patches()), 2)  # 変わらないので呼ばない

        self.clock[0] = local(3, 0); self.ops.maintenance_tick()
        self.assertEqual([p["enabled"] for p in self.patches()], [False, True, False])

    def test_saving_a_plan_in_the_future_does_not_start_maintenance(self):
        job = self.run_action("maintenance_set", self.planned(starts_at="2026-10-27T01:00:00", auto_resume_at="2026-10-27T03:00:00"))
        self.assertIn("いまは通常どおり", "\n".join(job.lines))
        self.assertFalse(any(p["enabled"] for p in self.patches()))

    def test_resaving_the_same_plan_does_not_call_cloudflare_again(self):
        params = self.planned(starts_at="2026-10-27T01:00:00", auto_resume_at="2026-10-27T03:00:00")
        self.run_action("maintenance_set", params)
        self.run_action("maintenance_set", params)
        self.assertEqual(len(self.patches()), 1)

    # --- 失敗と未設定 -------------------------------------------------------

    def test_permission_errors_are_reported_and_retried_later(self):
        self.fake.deny_patch = True
        with self.assertRaises(OpsError) as raised:
            self.run_action("maintenance_on", {"message": "x"})
        self.assertIn("権限が足りません", str(raised.exception))
        self.assertIn("再試行", str(raised.exception))
        self.assertIn("権限", self.state()["last_error"])
        self.assertEqual(self.state()["schedule"]["mode"], "emergency")  # 予定は残る

        self.fake.deny_patch = False
        calls = len(self.patches())
        self.tick(seconds=10)  # まだ待つ時間
        self.assertEqual(len(self.fake.calls("PATCH")), calls + 0)
        self.tick(seconds=30)
        self.assertTrue(self.state()["applied"]["enabled"])
        self.assertEqual(self.state()["last_error"], "")

    def test_cloudflare_outages_do_not_stop_the_operator(self):
        self.fake.fail_patch = True
        with self.assertRaises(OpsError):
            self.run_action("maintenance_on", {"message": "x"})
        self.tick(seconds=31)  # 例外を外に出さない
        self.assertTrue(self.state()["last_error"])

    def test_without_settings_manual_toggles_fail_clearly_but_plans_are_just_saved(self):
        (self.home / "cloudflare.env").unlink()
        with self.assertRaises(OpsError) as raised:
            self.run_action("maintenance_on", {"message": "x"})
        self.assertIn("setup.sh", str(raised.exception))

        job = self.run_action("maintenance_set", self.planned())
        self.assertIn("未設定", "\n".join(job.lines))
        self.assertFalse(self.state()["configured"])
        self.assertEqual(self.fake.requests, [])
        self.ops.maintenance_tick()  # 毎秒呼ばれても、何も起きない
        self.assertEqual(self.fake.requests, [])

    def test_incomplete_settings_are_treated_as_unconfigured(self):
        self.configure(CF_RULE_ID="")
        with self.assertRaises(OpsError):
            self.run_action("maintenance_on", {"message": "x"})
        self.assertEqual(self.fake.requests, [])

    def test_the_api_token_never_leaks_into_results_or_state(self):
        self.fake.deny_patch = True
        with self.assertRaises(OpsError):
            self.run_action("maintenance_on", {"message": "x"})
        with self.assertRaises(OpsError):
            self.run_action("maintenance_set", self.planned(starts_at="2026-10-26T00:00:01"))
        job = self.job("maintenance_on")
        job.emit("結果")
        job.write("failed", finished=True)
        for path in (self.home / "spool").rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN, path.read_text(errors="ignore"), path)

    def test_a_wrong_token_is_explained(self):
        self.configure(CF_API_TOKEN="wrong")
        with self.assertRaises(OpsError) as raised:
            self.run_action("maintenance_on", {"message": "x"})
        self.assertIn("トークンが無効", str(raised.exception))

    def test_requests_go_through_the_normal_job_path(self):
        request_id = protocol.submit(self.home / "spool", "maintenance_on", {"message": "テスト"}, source="rescue", now=self.clock[0])
        self.ops.process_pending()
        result = json.loads((self.home / "spool" / "results" / f"{request_id}.json").read_text())
        self.assertEqual(result["status"], protocol.SUCCEEDED)
        self.assertTrue(self.state()["applied"]["enabled"])
        self.assertEqual(self.state()["updated_by"], "rescue")


if __name__ == "__main__":
    unittest.main()
