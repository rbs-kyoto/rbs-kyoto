"""救出画面（rescue/、PHP）のテスト。本物の PHP サーバーを立てて HTTP で確かめる。

救出画面が書く依頼を、operator 側の protocol.validate が受け付けること（PHP と Python の
取り決めが食い違っていないこと）も確かめる。php が無い環境ではスキップする。
"""

import http.cookiejar
import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import protocol

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "rescue-pass-123"
BACKUP_ID = "20261025-050000-pre-update"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which("php"), "php がありません")
class RescueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        cls.spool = cls.root / "spool"
        cls.backups = cls.root / "backups"
        for name in ("requests", "results"):
            (cls.spool / name).mkdir(parents=True)
        (cls.backups / BACKUP_ID).mkdir(parents=True)
        (cls.backups / BACKUP_ID / "meta.json").write_text(
            json.dumps({"id": BACKUP_ID, "label": "pre-update", "created_at": "2026-10-25T05:00:00"})
        )
        password_hash = subprocess.run(
            ["php", "-r", f'echo password_hash("{PASSWORD}", PASSWORD_DEFAULT);'], capture_output=True, text=True, check=True
        ).stdout
        (cls.root / "hash").write_text(password_hash)
        (cls.root / "tmp").mkdir()
        cls.port = free_port()
        env = {
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(cls.root / "tmp"),
            "RESCUE_PASSWORD_FILE": str(cls.root / "hash"),
            "RESCUE_SPOOL": str(cls.spool),
            "RESCUE_BACKUPS": str(cls.backups),
            "RESCUE_ADMIN_HEALTH_URL": f"http://127.0.0.1:{free_port()}/healthz/",
        }
        cls.server = subprocess.Popen(
            ["php", "-d", f"session.save_path={cls.root / 'tmp'}", "-S", f"127.0.0.1:{cls.port}", "-t", str(ROOT / "rescue" / "public"),
             str(ROOT / "rescue" / "public" / "index.php")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        # ログインの失敗回数は一時フォルダに残るので、テストごとに消す
        for path in (self.root / "tmp").glob("rbs-rescue-failures.json"):
            path.unlink()
        for path in (self.spool / "requests").glob("*"):
            path.unlink()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def request(self, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            with self.opener.open(f"http://127.0.0.1:{self.port}{path}", body, timeout=10) as response:
                return response.status, response.read().decode(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode(), error.headers

    def csrf(self, html):
        return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)

    def login(self, password=PASSWORD):
        _, html, _ = self.request("/rescue/")
        return self.request("/rescue/", {"csrf": self.csrf(html), "password": password})

    def dashboard(self):
        status, html, _ = self.request("/rescue/")
        self.assertEqual(status, 200)
        return html

    def requests_written(self):
        return [json.loads(path.read_text()) for path in sorted((self.spool / "requests").glob("*.json"))]

    def test_login_screen_is_shown_without_any_controls(self):
        status, html, headers = self.request("/rescue/")
        self.assertEqual(status, 200)
        self.assertIn("ログイン", html)
        self.assertNotIn("更新前に戻す", html)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("no-store", headers["Cache-Control"])

    def test_actions_are_refused_without_login(self):
        _, html, _ = self.request("/rescue/")
        status, _, _ = self.request("/rescue/run", {"csrf": self.csrf(html), "action": "rollback", "confirm": "復元"})
        self.assertEqual(status, 200)  # ログイン画面に戻される
        self.assertEqual(self.requests_written(), [])

    def test_wrong_password_is_rejected_and_correct_one_logs_in(self):
        status, html, _ = self.login("wrong")
        self.assertIn("パスワードが違います", html)
        status, _, headers = self.login()
        self.assertEqual(status, 303)
        self.assertIn("更新前の状態に戻す", self.dashboard())

    def test_repeated_failures_lock_out_even_the_right_password(self):
        for _ in range(5):
            self.login("wrong")
        _, html, _ = self.login()
        self.assertIn("しばらくログインできません", html)
        self.assertNotIn("更新前に戻す", self.dashboard())

    def test_dashboard_reports_django_down_and_lists_backups(self):
        self.login()
        html = self.dashboard()
        self.assertIn("応答しません", html)
        self.assertIn(BACKUP_ID, html)
        self.assertIn("2026-10-25 05:00", html)

    def test_rollback_needs_the_confirmation_word(self):
        self.login()
        csrf = self.csrf(self.dashboard())
        _, html, _ = self.request("/rescue/run", {"csrf": csrf, "action": "rollback"})
        self.assertIn("「復元」と入力してください", html)
        self.assertEqual(self.requests_written(), [])

    def test_requests_are_rejected_without_a_valid_csrf_token(self):
        self.login()
        status, _, _ = self.request("/rescue/run", {"csrf": "forged", "action": "backup"})
        self.assertEqual(status, 303)
        self.assertEqual(self.requests_written(), [])

    def test_every_request_it_writes_passes_the_operators_validation(self):
        self.login()
        csrf = self.csrf(self.dashboard())
        submissions = [
            {"action": "rollback", "confirm": "復元"},
            {"action": "restore", "backup": BACKUP_ID, "confirm": "復元"},
            {"action": "restart", "service": "admin"},
            {"action": "restart", "service": "web"},
            {"action": "logs", "service": "opsd", "lines": "200"},
            {"action": "backup"},
        ]
        for data in submissions:
            with self.subTest(data=data):
                status, _, headers = self.request("/rescue/run", {"csrf": csrf, **data})
                self.assertEqual(status, 303)
                self.assertRegex(headers["Location"], r"/rescue/\?watch=\d{14}-[0-9a-f]{8}$")

        written = self.requests_written()
        self.assertCountEqual(
            [item["action"] for item in written], ["rollback", "restore", "restart", "restart", "logs", "backup"]
        )
        self.assertEqual(len(written), len(submissions))
        for item in written:
            self.assertEqual(item["source"], "rescue")
            self.assertTrue(protocol.REQUEST_ID_RE.fullmatch(item["id"]))
            self.assertEqual(protocol.validate(item["action"], item["params"]), item["params"])

    def test_malicious_parameters_are_refused_before_reaching_the_spool(self):
        self.login()
        csrf = self.csrf(self.dashboard())
        bad = [
            {"action": "restore", "backup": "../../etc/passwd", "confirm": "復元"},
            {"action": "restore", "backup": "20261025-050000-pre-update; reboot", "confirm": "復元"},
            {"action": "restart", "service": "opsd"},
            {"action": "restart", "service": "admin web"},
            {"action": "logs", "service": "admin", "lines": "99999"},
            {"action": "logs", "service": "admin", "lines": "5; rm"},
            {"action": "update_admin"},
            {"action": "shell"},
        ]
        for data in bad:
            with self.subTest(data=data):
                status, html, _ = self.request("/rescue/run", {"csrf": csrf, **data})
                self.assertEqual(status, 200)
                self.assertIn('class="error"', html)
        self.assertEqual(self.requests_written(), [])

    def test_result_page_shows_operator_output_escaped(self):
        self.login()
        request_id = protocol.new_request_id()
        (self.spool / "results" / f"{request_id}.json").write_text(
            json.dumps({"id": request_id, "action": "logs", "status": "succeeded", "output": "<script>alert(1)</script>"})
        )
        _, html, _ = self.request(f"/rescue/?watch={request_id}")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)", html)
        status, _, _ = self.request("/rescue/?watch=../../etc/passwd")
        self.assertEqual(status, 200)

    def test_logout_ends_the_session(self):
        self.login()
        csrf = self.csrf(self.dashboard())
        self.request("/rescue/logout", {"csrf": csrf})
        status, html, _ = self.request("/rescue/")
        self.assertNotIn("更新前の状態に戻す", html)
        self.assertIn("ログイン", html)


@unittest.skipUnless(shutil.which("php"), "php がありません")
class DownPageTests(unittest.TestCase):
    """管理画面に繋がらないときの案内。Cloudflare に差し替えられない 503 で返す。"""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = subprocess.Popen(
            ["php", "-S", f"127.0.0.1:{cls.port}", "-t", str(ROOT / "rescue" / "public")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)

    def test_it_answers_503_with_retry_after_and_the_guidance(self):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/down.php", timeout=10)
        except urllib.error.HTTPError as error:
            body = error.read().decode()
            self.assertEqual(error.code, 503)
            self.assertEqual(error.headers["Retry-After"], "30")
            self.assertIn("no-store", error.headers["Cache-Control"])
            self.assertIn("管理画面に繋がりません", body)
            self.assertIn('href="/rescue/"', body)
            self.assertIn('http-equiv="refresh"', body)
        else:
            self.fail("503 になるはずです")

    def test_the_static_page_is_still_available_for_other_uses(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/down.html", timeout=10) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
