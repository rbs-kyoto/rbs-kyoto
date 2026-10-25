"""テスト専用の、Cloudflare API に似せた小さなサーバー。

本物の Cloudflare には繋がず、「どんな API を、どんな内容で呼んだか」を記録して、
ドキュメントどおりの形で答える。次のような、実際に起きる失敗も再現できる:
  - 権限不足（deny_patch=True）、障害（fail_patch=True）
  - 「ルール1つの更新（PATCH）」は、全項目を送らないと 400 を返す（公式の仕様）
  - 「ルールセット全体の置き換え（PUT）」が呼ばれたら記録する（ほかのルールが消えるので、呼んではいけない）
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PHASE_PATH = "/rulesets/phases/http_request_dynamic_redirect/entrypoint"
REQUIRED_RULE_FIELDS = ("action", "expression", "action_parameters", "enabled")


class FakeCloudflare:
    def __init__(self, token="good-token", zones=None, subdomain=None, rules=None):
        self.token = token
        self.zones = zones if zones is not None else {"clusters-prj.com": {"id": "zone1", "account": {"id": "acct1"}}}
        self.subdomain = subdomain
        self.ruleset = {"id": "ruleset1", "rules": list(rules)} if rules is not None else None
        self.requests = []
        self.put_called = False
        self.deny_patch = False
        self.fail_patch = False
        self._counter = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode()) if length else None
                with fake._lock:
                    status, payload = fake.route(self.command, self.path, body, self.headers.get("Authorization", ""))
                    fake.requests.append((self.command, self.path, body))
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    # --- 応答 -------------------------------------------------------------

    @staticmethod
    def ok(result):
        return 200, {"success": True, "errors": [], "messages": [], "result": result}

    @staticmethod
    def error(status, message):
        return status, {"success": False, "errors": [{"code": status, "message": message}], "result": None}

    def new_id(self, prefix):
        self._counter += 1
        return f"{prefix}{self._counter}"

    def calls(self, method=None, contains=""):
        return [(m, p, b) for m, p, b in self.requests if (method is None or m == method) and contains in p]

    def route(self, method, raw_path, body, authorization):
        if authorization != f"Bearer {self.token}":
            return self.error(401, "Invalid API Token")
        url = urlparse(raw_path)
        path = url.path.removeprefix("/client/v4")

        if method == "GET" and path == "/zones":
            name = parse_qs(url.query).get("name", [""])[0]
            zone = self.zones.get(name)
            return self.ok([{"id": zone["id"], "name": name, "account": zone["account"]}] if zone else [])

        match = re.fullmatch(r"/accounts/([^/]+)/workers/subdomain", path)
        if match:
            if method == "GET":
                return self.ok({"subdomain": self.subdomain}) if self.subdomain else self.error(404, "no subdomain")
            if method == "PUT":
                self.subdomain = body["subdomain"]
                return self.ok({"subdomain": self.subdomain})

        match = re.fullmatch(r"/zones/([^/]+)(/.*)", path)
        if not match:
            return self.error(404, "not found")
        rest = match.group(2)

        if method == "GET" and rest == PHASE_PATH:
            return self.ok(self.ruleset) if self.ruleset else self.error(404, "no entrypoint")

        if method == "POST" and rest == "/rulesets":
            self.ruleset = {"id": "ruleset1", "phase": body["phase"], "rules": []}
            for rule in body["rules"]:
                self.ruleset["rules"].append({**rule, "id": self.new_id("rule")})
            return self.ok(self.ruleset)

        match = re.fullmatch(r"/rulesets/([^/]+)(/rules(?:/([^/]+))?)?", rest)
        if match and self.ruleset and match.group(1) == self.ruleset["id"]:
            rule_id = match.group(3)
            if method == "POST" and match.group(2) == "/rules":
                self.ruleset["rules"].append({**body, "id": self.new_id("rule")})
                return self.ok(self.ruleset)
            if method == "PATCH" and rule_id:
                if self.deny_patch:
                    return self.error(403, "Authentication error")
                if self.fail_patch:
                    return self.error(500, "internal error")
                missing = [field for field in REQUIRED_RULE_FIELDS if field not in body]
                if missing:
                    return self.error(400, f"rule is missing fields: {', '.join(missing)}")
                for index, rule in enumerate(self.ruleset["rules"]):
                    if rule["id"] == rule_id:
                        self.ruleset["rules"][index] = {**body, "id": rule_id}
                        return self.ok(self.ruleset)
                return self.error(404, "rule not found")
            if method == "PUT" and not match.group(2):
                self.put_called = True
                self.ruleset["rules"] = list(body.get("rules", []))
                return self.ok(self.ruleset)
        return self.error(404, "not found")
