import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from . import protocol
from .daemon import Config, Job, Ops, OpsError

HEALTHY = "running healthy"


class FakeDocker:
    """docker / git を実際には動かさず、呼ばれたコマンドを記録して決めた答えを返す。"""

    def __init__(self):
        self.calls = []
        self.images = {"rbs-admin:current": "sha256:old-admin", "rbs-web:current": "sha256:old-web"}
        self.commit = "aaaa111"
        self.pulled_commit = "bbbb222"
        self.health = [HEALTHY]
        self.fail = {}  # コマンドに含まれる文字列 -> 終了コード
        self.changed_files = ""

    def __call__(self, cmd, timeout, cwd=None):
        self.calls.append(list(cmd))
        text = " ".join(cmd)
        for needle, code in self.fail.items():
            if needle in text:
                return code, f"{needle} が失敗しました"
        if cmd[:3] == ["docker", "image", "inspect"]:
            image = cmd[-1]
            if image in self.images:
                return 0, self.images[image] + "\n"
            if image.startswith("sha256:"):
                return 0, image + "\n"
            return 1, "No such image"
        if cmd[:2] == ["docker", "inspect"]:
            return 0, (self.health.pop(0) if len(self.health) > 1 else self.health[0]) + "\n"
        if cmd[:2] == ["docker", "tag"]:
            self.images[cmd[3]] = cmd[2] if cmd[2].startswith("sha256:") else self.images.get(cmd[2], "sha256:" + cmd[2])
            return 0, ""
        if "rev-parse" in cmd:
            return 0, self.commit + "\n"
        if cmd[3:5] == ["pull", "--ff-only"]:
            self.commit = self.pulled_commit
            return 0, "Updating"
        if "diff" in cmd:
            return 0, self.changed_files
        if "build" in cmd and "rbs-admin" not in text:
            self.images["rbs-admin:current"] = "sha256:new-admin"
        return 0, ""

    def commands(self, *needles):
        return [" ".join(call) for call in self.calls if all(needle in " ".join(call) for needle in needles)]


class OpsTestCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.config = Config(home=self.home, health_timeout=3)
        self.docker = FakeDocker()
        self.clock = [datetime(2026, 10, 25, 4, 0, 0)]
        self.ops = Ops(self.config, runner=self.docker, now=lambda: self.clock[0], sleep=lambda seconds: None)
        self.ops.recover()
        self.config.data_dir.mkdir(parents=True)
        (self.config.media / "pickup").mkdir(parents=True)
        (self.config.media / "pickup" / "a.png").write_bytes(b"image-a")
        self.write_db(["first"])

    def write_db(self, titles):
        connection = sqlite3.connect(self.config.db)
        connection.execute("drop table if exists news")
        connection.execute("create table news (title text)")
        connection.executemany("insert into news values (?)", [(title,) for title in titles])
        connection.commit()
        connection.close()

    def titles(self):
        connection = sqlite3.connect(self.config.db)
        try:
            return [row[0] for row in connection.execute("select title from news order by rowid")]
        finally:
            connection.close()

    def job(self, action="backup", params=None):
        return Job(self.ops, {"id": protocol.new_request_id(self.clock[0]), "action": action, "params": params or {}})

    def tick(self, seconds=1):
        from datetime import timedelta

        self.clock[0] += timedelta(seconds=seconds)


class ProtocolTests(unittest.TestCase):
    def test_valid_requests_are_normalized(self):
        self.assertEqual(protocol.validate("backup", None), {})
        self.assertEqual(protocol.validate("restart", {"service": "web", "junk": 1}), {"service": "web"})
        self.assertEqual(protocol.validate("logs", {"service": "opsd"}), {"service": "opsd", "lines": 200})
        self.assertEqual(
            protocol.validate("restore", {"backup": "20261025-040000-pre-update"}),
            {"backup": "20261025-040000-pre-update"},
        )

    def test_invalid_requests_are_rejected(self):
        bad = [
            ("shell", {}),
            ("restart", {"service": "opsd"}),
            ("restart", {"service": "admin; rm -rf /"}),
            ("logs", {"service": "admin", "lines": 0}),
            ("logs", {"service": "admin", "lines": 1001}),
            ("logs", {"service": "admin", "lines": "5"}),
            ("logs", {"service": "admin", "lines": True}),
            ("restore", {"backup": "../../etc"}),
            ("restore", {"backup": "20261025-040000-UPPER"}),
            ("restore", {}),
            ("backup", "x"),
        ]
        for action, params in bad:
            with self.subTest(action=action, params=params):
                with self.assertRaises(ValueError):
                    protocol.validate(action, params)

    def test_submit_and_read_status(self):
        spool = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, spool, ignore_errors=True)
        request_id = protocol.submit(spool, "restart", {"service": "admin"}, source="django:staff")

        status = protocol.read_status(spool, request_id)
        self.assertEqual(status["status"], protocol.QUEUED)
        self.assertEqual(status["params"], {"service": "admin"})
        self.assertEqual(status["source"], "django:staff")
        self.assertIsNone(protocol.read_status(spool, "../../etc/passwd"))
        self.assertEqual([item["id"] for item in protocol.list_recent(spool)], [request_id])

    def test_submit_rejects_bad_requests_without_writing(self):
        spool = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, spool, ignore_errors=True)
        with self.assertRaises(ValueError):
            protocol.submit(spool, "restart", {"service": "x"})
        self.assertFalse(list((spool / "requests").glob("*")) if (spool / "requests").exists() else [])


class BackupTests(OpsTestCase):
    def test_backup_copies_db_and_links_media_and_records_versions(self):
        job = self.job()
        backup_id = self.ops.backup(job, "manual")

        directory = self.config.backups / backup_id
        meta = json.loads((directory / "meta.json").read_text())
        self.assertEqual(meta["admin_image"], "sha256:old-admin")
        self.assertEqual(meta["git_commit"], "aaaa111")
        self.assertTrue(meta["has_db"])
        self.assertEqual((directory / "media" / "pickup" / "a.png").read_bytes(), b"image-a")
        self.assertEqual(sqlite3.connect(directory / "db.sqlite3").execute("select title from news").fetchall(), [("first",)])
        self.assertEqual([m["id"] for m in protocol.list_backups(self.config.backups)], [backup_id])

    def test_backup_is_a_snapshot_not_a_live_link(self):
        backup_id = self.ops.backup(self.job(), "manual")
        self.write_db(["first", "second"])

        copied = sqlite3.connect(self.config.backups / backup_id / "db.sqlite3")
        self.assertEqual(copied.execute("select count(*) from news").fetchone()[0], 1)

    def test_two_backups_in_the_same_second_get_different_ids(self):
        first = self.ops.backup(self.job(), "manual")
        second = self.ops.backup(self.job(), "manual")
        self.assertNotEqual(first, second)

    def test_old_backups_are_pruned_per_label(self):
        for _ in range(16):
            self.ops.backup(self.job(), "daily")
            self.tick()
        self.ops.backup(self.job(), "pre-update")

        labels = [meta["label"] for meta in protocol.list_backups(self.config.backups)]
        self.assertEqual(labels.count("daily"), 14)
        self.assertEqual(labels.count("pre-update"), 1)

    def test_failed_backup_leaves_no_half_written_directory(self):
        (self.config.db).write_bytes(b"not a sqlite database at all")
        with self.assertRaises(Exception):
            self.ops.backup(self.job(), "manual")
        self.assertEqual([path.name for path in self.config.backups.iterdir()], [])

    def test_bad_label_is_rejected(self):
        with self.assertRaises(OpsError):
            self.ops.backup(self.job(), "../x")


class RestoreTests(OpsTestCase):
    def test_restore_brings_back_data_media_and_admin_image(self):
        backup_id = self.ops.backup(self.job(), "pre-update")
        self.tick()
        self.write_db(["first", "added later"])
        (self.config.media / "pickup" / "b.png").write_bytes(b"image-b")
        self.docker.images["rbs-admin:current"] = "sha256:broken-admin"

        job = self.job("restore", {"backup": backup_id})
        self.ops.restore(job, backup_id)

        self.assertEqual(self.titles(), ["first"])
        self.assertFalse((self.config.media / "pickup" / "b.png").exists())
        self.assertEqual((self.config.media / "pickup" / "a.png").read_bytes(), b"image-a")
        self.assertEqual(self.docker.images["rbs-admin:current"], "sha256:old-admin")
        order = [call for call in self.docker.commands() if "stop admin" in call or "up -d admin" in call or "docker tag" in call]
        self.assertIn("stop admin", order[0])
        self.assertIn("docker tag sha256:old-admin rbs-admin:current", order[1])
        self.assertIn("up -d admin", order[2])

    def test_restore_first_saves_the_current_state(self):
        backup_id = self.ops.backup(self.job(), "pre-update")
        self.tick()
        self.write_db(["first", "precious edit"])

        self.ops.restore(self.job(), backup_id)

        saved = [meta for meta in protocol.list_backups(self.config.backups) if meta["label"] == "before-restore"]
        self.assertEqual(len(saved), 1)
        copied = sqlite3.connect(self.config.backups / saved[0]["id"] / "db.sqlite3")
        self.assertEqual(copied.execute("select count(*) from news").fetchone()[0], 2)

    def test_restore_keeps_current_image_when_the_old_one_is_gone(self):
        backup_id = self.ops.backup(self.job(), "pre-update")
        meta_path = self.config.backups / backup_id / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["admin_image"] = "gone-image"
        meta_path.write_text(json.dumps(meta))
        self.docker.images.pop("gone-image", None)
        original = self.docker.__call__

        def runner(cmd, timeout, cwd=None):
            if cmd[:3] == ["docker", "image", "inspect"] and cmd[-1] == "gone-image":
                return 1, "No such image"
            return original(cmd, timeout, cwd)

        self.ops.runner = runner
        job = self.job()
        self.ops.restore(job, backup_id)

        self.assertIn("データだけ戻して", "\n".join(job.lines))

    def test_unknown_or_dataless_backup_fails_cleanly(self):
        with self.assertRaises(OpsError):
            self.ops.restore(self.job(), "20260101-000000-manual")
        (self.config.backups / "20260101-000000-manual").mkdir(parents=True)
        (self.config.backups / "20260101-000000-manual" / "meta.json").write_text('{"id": "20260101-000000-manual", "label": "manual"}')
        with self.assertRaises(OpsError):
            self.ops.restore(self.job(), "20260101-000000-manual")

    def test_rollback_uses_the_newest_pre_update_backup(self):
        self.ops.backup(self.job(), "pre-update")
        self.tick()
        self.write_db(["first", "second"])
        newest = self.ops.backup(self.job(), "pre-update")
        self.tick()
        self.write_db(["first", "second", "third"])

        self.ops.rollback(self.job())

        self.assertEqual(self.titles(), ["first", "second"])
        self.assertTrue((self.config.backups / newest).exists())

    def test_rollback_without_pre_update_backup_explains(self):
        with self.assertRaises(OpsError) as raised:
            self.ops.rollback(self.job())
        self.assertIn("更新前", str(raised.exception))

    def test_restore_fails_if_admin_does_not_become_healthy(self):
        backup_id = self.ops.backup(self.job(), "manual")
        self.docker.health = ["running unhealthy"]
        with self.assertRaises(OpsError) as raised:
            self.ops.restore(self.job(), backup_id)
        self.assertIn("正常に起動しませんでした", str(raised.exception))


class UpdateTests(OpsTestCase):
    def test_admin_update_backs_up_builds_migrates_then_starts(self):
        job = self.job("update_admin")
        self.ops.update(job, "admin")

        commands = self.docker.commands()
        labels = [meta["label"] for meta in protocol.list_backups(self.config.backups)]
        self.assertEqual(labels, ["pre-update"])
        build = next(i for i, c in enumerate(commands) if " build --pull admin" in c)
        migrate = next(i for i, c in enumerate(commands) if "run --rm --no-deps admin python manage.py migrate" in c)
        up = next(i for i, c in enumerate(commands) if " up -d admin" in c)
        stop = next(i for i, c in enumerate(commands) if " stop admin" in c)
        self.assertLess(build, stop)
        self.assertLess(stop, migrate)
        self.assertLess(migrate, up)
        self.assertTrue(any("docker tag rbs-admin:current rbs-admin:previous" in c for c in commands))

    @unittest.skipUnless(os.geteuid() == 0, "持ち主を変えるには root が必要")
    def test_update_hands_the_media_folder_to_the_app_user(self):
        # Docker が media を root 持ちで作ってしまった状態（画像を保存できない）を直す
        config = Config(home=self.home, health_timeout=3, uid=12345, gid=12345)
        ops = Ops(config, runner=self.docker, now=lambda: self.clock[0], sleep=lambda seconds: None)
        ops.ensure_state_dirs()
        for directory in (config.data_dir, config.media, self.home / "state" / "site"):
            self.assertEqual(directory.stat().st_uid, 12345, directory)

    def test_web_update_does_not_touch_data_or_admin(self):
        self.ops.update(self.job("update_web"), "web")

        self.assertEqual(protocol.list_backups(self.config.backups), [])
        self.assertFalse(self.docker.commands("stop admin"))
        self.assertTrue(self.docker.commands("build --pull web"))

    def test_failed_update_rolls_back_code_image_and_data(self):
        self.docker.health = ["running unhealthy", HEALTHY]  # 新しい版は不健康、戻した版は健康

        def break_things_during_build(cmd, timeout, cwd=None, original=self.docker.__call__):
            if "migrate" in cmd:
                self.write_db(["first", "migrated and then broken"])
                self.docker.images["rbs-admin:current"] = "sha256:new-broken"
            return original(cmd, timeout, cwd)

        self.ops.runner = break_things_during_build
        job = self.job("update_admin")
        with self.assertRaises(OpsError) as raised:
            self.ops.update(job, "admin")

        self.assertIn("元の版に戻しました", str(raised.exception))
        self.assertEqual(self.titles(), ["first"])
        self.assertTrue(self.docker.commands("git", "reset --hard aaaa111"))
        self.assertTrue(self.docker.commands("docker tag rbs-admin:previous rbs-admin:current"))
        self.assertIn("元の版に戻しました。", job.lines)

    def test_update_falls_back_to_the_local_base_image_when_the_registry_is_down(self):
        self.docker.fail = {"build --pull admin": 1}
        job = self.job("update_admin")

        self.ops.update(job, "admin")

        self.assertIn("取得済みのもので作り直します", "\n".join(job.lines))
        self.assertTrue(any(c.endswith("build admin") for c in self.docker.commands("build")))
        self.assertTrue(self.docker.commands("up -d admin"))

    def test_build_failure_also_rolls_back(self):
        self.docker.fail = {"build": 1}
        with self.assertRaises(OpsError) as raised:
            self.ops.update(self.job("update_admin"), "admin")
        self.assertIn("元の版に戻しました", str(raised.exception))
        self.assertTrue(self.docker.commands("up -d admin"))

    def test_git_pull_failure_stops_before_building(self):
        self.docker.fail = {"pull --ff-only": 1}
        with self.assertRaises(OpsError):
            self.ops.update(self.job("update_admin"), "admin")
        self.assertFalse(self.docker.commands("build"))

    def test_failure_to_roll_back_points_to_the_rescue_screen(self):
        self.docker.health = ["running unhealthy"]
        with self.assertRaises(OpsError) as raised:
            self.ops.update(self.job("update_admin"), "admin")
        self.assertIn("/rescue/", str(raised.exception))

    def test_update_that_changes_opsd_asks_to_restart_the_operator(self):
        self.docker.changed_files = "opsd/daemon.py\n"
        self.ops.update(self.job("update_web"), "web")
        self.assertTrue(self.ops.restart_requested)


class DaemonLoopTests(OpsTestCase):
    def submit(self, action, params=None):
        return protocol.submit(self.config.spool, action, params, source="test", now=self.clock[0])

    def result(self, request_id):
        return json.loads((self.config.spool / "results" / f"{request_id}.json").read_text())

    def test_pending_requests_run_in_order_and_leave_results(self):
        first = self.submit("backup")
        self.tick()
        second = self.submit("logs", {"service": "opsd", "lines": 5})
        (self.config.spool / "logs" / "opsd.log").write_text("line1\nline2\n")

        self.ops.process_pending()

        self.assertEqual(self.result(first)["status"], protocol.SUCCEEDED)
        done = self.result(second)
        self.assertEqual(done["status"], protocol.SUCCEEDED)
        self.assertIn("line2", done["output"])
        self.assertEqual(list((self.config.spool / "requests").glob("*.json")), [])
        self.assertEqual(list((self.config.spool / "running").glob("*.json")), [])

    def test_invalid_request_file_fails_without_running_anything(self):
        request_id = protocol.new_request_id(self.clock[0])
        (self.config.spool / "requests" / f"{request_id}.json").write_text(
            json.dumps({"id": request_id, "action": "restart", "params": {"service": "$(reboot)"}})
        )
        self.ops.process_pending()

        self.assertEqual(self.result(request_id)["status"], protocol.FAILED)
        self.assertEqual(self.docker.calls, [])

    def test_garbage_files_are_discarded_or_failed_without_running_anything(self):
        requests = self.config.spool / "requests"
        (requests / "evil.json").write_text("{}")  # 依頼IDの形でないものは無視して捨てる
        (requests / "20261025040000-zzzzzzzz.json").write_text("{}")
        (requests / "20261025040001-aaaaaaaa.json").write_text("not json")  # 形は正しいが中身が壊れている

        self.ops.process_pending()

        self.assertEqual(list(requests.glob("*.json")), [])
        results = [path.name for path in (self.config.spool / "results").glob("*.json")]
        self.assertEqual(results, ["20261025040001-aaaaaaaa.json"])
        self.assertEqual(self.result("20261025040001-aaaaaaaa")["status"], protocol.FAILED)
        self.assertEqual(self.docker.calls, [])

    def test_unexpected_errors_do_not_stop_the_operator(self):
        request_id = self.submit("backup")
        self.config.db.write_bytes(b"corrupt")
        self.ops.process_pending()

        done = self.result(request_id)
        self.assertEqual(done["status"], protocol.FAILED)
        self.assertIn("想定外", done["output"])

    def test_interrupted_jobs_are_marked_failed_on_startup(self):
        request_id = protocol.new_request_id(self.clock[0])
        job = Job(self.ops, {"id": request_id, "action": "update_admin", "params": {}})
        job.emit("途中まで")
        self.assertEqual(self.result(request_id)["status"], protocol.RUNNING)

        self.ops.recover()

        done = self.result(request_id)
        self.assertEqual(done["status"], protocol.FAILED)
        self.assertIn("途中で止まりました", done["output"])

    def test_daily_backup_runs_once_after_the_set_hour(self):
        self.clock[0] = datetime(2026, 10, 25, 2, 59)
        self.ops.maintenance()
        self.assertEqual(protocol.list_backups(self.config.backups), [])

        self.clock[0] = datetime(2026, 10, 25, 3, 0)
        self.ops.maintenance()
        self.tick(60)
        self.ops.maintenance()
        self.assertEqual([m["label"] for m in protocol.list_backups(self.config.backups)], ["daily"])
        [recent] = protocol.list_recent(self.config.spool)
        self.assertEqual(recent["requested_at"], "2026-10-25T03:00:00")
        self.assertEqual(recent["source"], "opsd")

        self.clock[0] = datetime(2026, 10, 26, 3, 5)
        self.ops.maintenance()
        self.assertEqual(len(protocol.list_backups(self.config.backups)), 2)

    def test_result_output_is_capped(self):
        job = self.job()
        job.emit("x" * 30000)
        result = json.loads(job.result_path.read_text())
        self.assertLessEqual(len(result["output"]), 20100)
        self.assertTrue(result["output"].startswith("…"))


if __name__ == "__main__":
    unittest.main()
