"""公開側の入口（gate/、PHP）の振る舞いの仕様。本物の PHP サーバーを立てて、HTTP で確かめる。

返すページは、spec/golden/（書き出しの仕様）をそのまま使う。
どの言語で作り直しても、この表と同じ応答を返せば、公開側は同じ振る舞いになる。
php が無い環境ではスキップする。
"""

import http.client
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).parent / "golden"
SESSION_ID = "abcdef0123456789abcdef0123456789"
EXPIRED_ID = "0123456789abcdef0123456789abcdef"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_session(directory, session_id, email, login_at):
    user = f'a:2:{{s:5:"email";s:{len(email)}:"{email}";s:8:"login_at";i:{login_at};}}'
    (Path(directory) / f"sess_{session_id}").write_text(f"user|{user}")


@unittest.skipUnless(shutil.which("php"), "php がありません")
class GateSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        site = cls.root / "site"
        release = site / "releases" / "v1"
        release.parent.mkdir(parents=True)
        shutil.copytree(GOLDEN, release)
        (site / "current").symlink_to(release)
        sessions = cls.root / "sessions"
        sessions.mkdir()
        cls.sessions = sessions
        write_session(sessions, SESSION_ID, "member@example.com", int(time.time()))
        write_session(sessions, EXPIRED_ID, "old@example.com", int(time.time()) - 60 * 60 * 24 * 30)

        cls.port = free_port()
        env = {
            "PATH": "/usr/bin:/bin",
            "GATE_SITE_ROOT": str(site),
            "GATE_BASE_URL": "http://127.0.0.1",
            "GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GATE_ALLOWED_DOMAIN": "rakunan-h.ed.jp",
        }
        cls.server = subprocess.Popen(
            ["php", "-d", f"session.save_path={sessions}", "-S", f"127.0.0.1:{cls.port}", "-t", str(ROOT / "gate" / "public"),
             str(ROOT / "gate" / "public" / "index.php")],
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

    def get(self, path, session=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": f"rbs_gate={session}"} if session else {}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
        headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, headers, body

    def golden(self, name):
        return (GOLDEN / name).read_text(encoding="utf-8")

    # --- 誰に、どちらの版を返すか -------------------------------------------

    def test_visitors_get_the_public_version(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.golden("public/index.html"))
        self.assertEqual(headers["cache-control"], "no-cache")
        self.assertEqual(headers["vary"], "Cookie")

    def test_logged_in_members_get_the_members_version_and_it_is_never_cached(self):
        status, headers, body = self.get("/", SESSION_ID)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.golden("members/index.html"))
        self.assertEqual(headers["cache-control"], "private, no-store")

    def test_members_only_pages_send_visitors_to_login_and_remember_where_they_were(self):
        status, headers, _ = self.get("/manuals/?sort=date")
        self.assertEqual(status, 302)
        self.assertEqual(headers["location"], "/accounts/login/?next=" + urllib.parse.quote("/manuals/?sort=date", safe=""))
        self.assertEqual(headers["cache-control"], "no-store")

    def test_members_can_open_members_only_pages(self):
        for path, name in (
            ("/manuals/", "members/manuals/index.html"),
            ("/manuals/1/", "members/manuals/1/index.html"),
            ("/videos/", "members/videos/index.html"),
            ("/videos/year/2025/", "members/videos/year/2025/index.html"),
        ):
            with self.subTest(path=path):
                status, _, body = self.get(path, SESSION_ID)
                self.assertEqual((status, body), (200, self.golden(name)))

    def test_an_expired_session_is_a_visitor(self):
        status, headers, _ = self.get("/manuals/", EXPIRED_ID)
        self.assertEqual((status, headers["location"].split("?")[0]), (302, "/accounts/login/"))

    def test_an_unknown_session_cookie_is_a_visitor(self):
        status, _, body = self.get("/", "ffffffffffffffffffffffffffffffff")
        self.assertEqual((status, body), (200, self.golden("public/index.html")))

    # --- URLの規則 -------------------------------------------------------

    def test_query_pages_use_the_query_variant_and_unknown_queries_fall_back(self):
        _, _, page_two = self.get("/news/?page=2")
        self.assertEqual(page_two, self.golden("public/news/_q/page-2/index.html"))
        _, _, fallback = self.get("/news/?page=99")
        self.assertEqual(fallback, self.golden("public/news/index.html"))
        _, _, ignored = self.get("/news/?evil=1")
        self.assertEqual(ignored, self.golden("public/news/index.html"))

    def test_a_missing_trailing_slash_is_redirected_permanently(self):
        status, headers, _ = self.get("/news")
        self.assertEqual((status, headers["location"]), (301, "/news/"))
        status, headers, _ = self.get("/news?page=2")
        self.assertEqual((status, headers["location"]), (301, "/news/?page=2"))

    def test_unknown_and_unsafe_paths_are_404_with_the_error_page(self):
        for path in ("/nothing/", "/news/9999/", "/..%2f..%2fetc/passwd", "/a//b/", "/.git/config"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual((status, body), (404, self.golden("errors/404.html")))

    def test_inactive_and_internal_content_is_not_reachable_by_visitors(self):
        # 部内限定の記事（members だけにある）は、未ログインなら、ログインへ。非公開の記事は、誰にも 404
        status, headers, _ = self.get("/news/2/")
        self.assertEqual((status, headers["location"].split("?")[0]), (302, "/accounts/login/"))
        self.assertEqual(self.get("/news/3/", SESSION_ID)[0], 404)

    def test_head_requests_return_headers_only(self):
        status, headers, body = self.get("/", method="HEAD")
        self.assertEqual((status, body), (200, ""))
        self.assertEqual(headers["cache-control"], "no-cache")

    # --- ログイン・ログアウト -----------------------------------------------

    def test_mypage_shows_the_logged_in_email_escaped(self):
        status, _, body = self.get("/accounts/mypage/", SESSION_ID)
        self.assertEqual(status, 200)
        self.assertIn("member@example.com", body)
        self.assertNotIn("<!--RBS_GATE_EMAIL-->", body)

    def test_the_login_page_for_a_logged_in_user_goes_to_a_safe_next_only(self):
        for next_value, expected in (("/manuals/", "/manuals/"), ("//evil.example/", "/"), ("https://evil.example/", "/"), ("/a\\b", "/")):
            with self.subTest(next=next_value):
                status, headers, _ = self.get("/accounts/login/?next=" + urllib.parse.quote(next_value, safe=""), SESSION_ID)
                self.assertEqual((status, headers["location"]), (302, expected))

    def test_the_login_page_for_a_visitor_is_the_public_login_page(self):
        status, headers, body = self.get("/accounts/login/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "private, no-store")
        self.assertNotIn("<!--RBS_GATE_MESSAGE-->", body)

    def test_logout_ends_the_session_and_returns_home(self):
        # ログアウトはセッションを消すので、ほかのテストと共有しない別のセッションを使う
        other = "11112222333344445555666677778888"
        write_session(self.sessions, other, "bye@example.com", int(time.time()))
        status, headers, _ = self.get("/accounts/logout/", other)
        self.assertEqual((status, headers["location"]), (302, "/"))
        self.assertIn("rbs_gate=", headers.get("set-cookie", ""))
        self.assertEqual(self.get("/manuals/", other)[0], 302)

    def test_starting_google_login_sends_the_right_parameters(self):
        status, headers, _ = self.get("/accounts/google/login/")
        self.assertEqual(status, 302)
        location = urllib.parse.urlparse(headers["location"])
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", "https://accounts.google.com/o/oauth2/v2/auth")
        self.assertEqual(query["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1/accounts/google/login/callback/"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["hd"], ["rakunan-h.ed.jp"])
        self.assertTrue(query["state"][0] and query["nonce"][0])

    def test_a_callback_without_a_started_login_is_refused(self):
        status, headers, _ = self.get("/accounts/google/login/callback/?code=x&state=y")
        self.assertEqual(status, 302)
        self.assertTrue(headers["location"].startswith("/accounts/login/"))

    # --- そのほか -------------------------------------------------------

    def test_healthz(self):
        self.assertEqual(self.get("/healthz")[::2], (200, "ok"))

    def test_without_a_published_release_the_site_says_it_is_not_ready(self):
        (self.root / "site" / "current").unlink()
        try:
            status, headers, _ = self.get("/")
            self.assertEqual((status, headers["retry-after"]), (503, "300"))
        finally:
            (self.root / "site" / "current").symlink_to(self.root / "site" / "releases" / "v1")

    def test_switching_the_published_release_takes_effect_immediately(self):
        other = self.root / "site" / "releases" / "v2"
        shutil.copytree(GOLDEN, other)
        (other / "public" / "index.html").write_text("v2のトップ", encoding="utf-8")
        current = self.root / "site" / "current"
        try:
            self.assertEqual(self.get("/")[2], self.golden("public/index.html"))
            current.unlink()
            current.symlink_to(other)
            self.assertEqual(self.get("/")[2], "v2のトップ")
        finally:
            current.unlink()
            current.symlink_to(self.root / "site" / "releases" / "v1")
