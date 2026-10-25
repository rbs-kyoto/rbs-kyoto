"""Cloudflare の API（標準ライブラリだけ）。

メンテナンス画面は、Cloudflare のリダイレクトルール（Single Redirects）1つの「有効／無効」で
切り替える。有効な間、公開サイトへのアクセスは、固定ページ（Workers の静的配信）に飛ぶ。
サイトの前に立つのは Cloudflare なので、サーバーやコンテナが落ちていても働く。

- ルールは API で「足す（POST）」「1つだけ更新する（PATCH）」だけを使う。
  ルールセット全体を置き換える（PUT）と、ほかのリダイレクトルールが消えるため使わない。
- PATCH は、変えない項目も含めて全項目を送る必要がある（公式の仕様）。
"""

import json
import re
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://api.cloudflare.com/client/v4"
PHASE = "http_request_dynamic_redirect"
RULE_REF = "rbs_maintenance"
RULE_DESCRIPTION = "rbs京都: メンテナンス画面へ（opsd が有効・無効を切り替える。手で消さないでください）"
USER_AGENT = "rbs-kyoto-opsd/1.0"
HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
MAX_QUERY_TEXT = 200


class CloudflareError(Exception):
    """利用者に見せてよいメッセージを持つ失敗。"""


class Client:
    def __init__(self, token, base=DEFAULT_BASE, opener=urllib.request.urlopen, timeout=20):
        self.token = token
        self.base = base.rstrip("/")
        self.opener = opener
        self.timeout = timeout

    def call(self, method, path, body=None, allow_404=False):
        """Cloudflare の API を呼んで、レスポンスの "result" を返す。allow_404 なら 404 は None。"""
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_404:
                return None
            raise CloudflareError(self._describe(error.code, error.read())) from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise CloudflareError(f"Cloudflare に繋がりませんでした（{error}）。") from None
        if not payload.get("success", True):
            raise CloudflareError(self._describe(200, json.dumps(payload).encode()))
        return payload.get("result")

    @staticmethod
    def _describe(status, raw):
        try:
            errors = json.loads(raw.decode() or "{}").get("errors") or []
            detail = "; ".join(str(error.get("message", error)) for error in errors)
        except (ValueError, AttributeError):
            detail = ""
        hints = {
            401: "トークンが無効です。",
            403: "トークンの権限が足りません（Zone の「Single Redirect」の編集権限が必要です）。",
        }
        return f"Cloudflare がエラーを返しました（{status}）。{hints.get(status, '')}{detail}".strip()

    # --- ゾーン・サブドメイン ---------------------------------------------

    def find_zone(self, host):
        """host（サブドメインでもよい）を含む、登録済みのゾーンを返す。"""
        labels = host.lower().rstrip(".").split(".")
        for start in range(len(labels) - 1):
            name = ".".join(labels[start:])
            zones = self.call("GET", "/zones?" + urllib.parse.urlencode({"name": name}))
            if zones:
                zone = zones[0]
                return {"id": zone["id"], "name": zone["name"], "account_id": zone["account"]["id"]}
        raise CloudflareError(
            f"{host} を含むゾーンが、このトークンから見つかりません。トークンの対象ゾーンを確認してください。"
        )

    def workers_subdomain(self, account_id):
        result = self.call("GET", f"/accounts/{account_id}/workers/subdomain", allow_404=True)
        return (result or {}).get("subdomain") or None

    def set_workers_subdomain(self, account_id, name):
        result = self.call("PUT", f"/accounts/{account_id}/workers/subdomain", {"subdomain": name})
        return (result or {}).get("subdomain") or name

    # --- リダイレクトルール -------------------------------------------------

    def entrypoint(self, zone_id):
        return self.call("GET", f"/zones/{zone_id}/rulesets/phases/{PHASE}/entrypoint", allow_404=True)

    def create_entrypoint(self, zone_id, rule):
        return self.call(
            "POST",
            f"/zones/{zone_id}/rulesets",
            {"name": "Redirect rules", "kind": "zone", "phase": PHASE, "rules": [rule]},
        )

    def add_rule(self, zone_id, ruleset_id, rule):
        return self.call("POST", f"/zones/{zone_id}/rulesets/{ruleset_id}/rules", rule)

    def update_rule(self, zone_id, ruleset_id, rule_id, rule):
        return self.call("PATCH", f"/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}", rule)


def _expression_string(value):
    """ルールの式の中に入れる文字列。引用符とバックスラッシュを含むものは受け付けない。"""
    if '"' in value or "\\" in value or "\n" in value:
        raise CloudflareError("設定に使えない文字が含まれています。")
    return f'"{value}"'


def clean_text(text, limit=MAX_QUERY_TEXT):
    """画面に出す文。改行や連続する空白を1つにして、長さを切る。"""
    return " ".join(str(text or "").split())[:limit]


def build_rule(*, hosts, maintenance_url, enabled, message="", until=""):
    """メンテナンス画面へ飛ばすルール（PATCH で全項目を送るので、毎回この形で組み立てる）。"""
    hosts = [host.strip().lower() for host in hosts if host.strip()]
    if not hosts or not all(HOST_RE.fullmatch(host) for host in hosts):
        raise CloudflareError("公開サイトのホスト名の設定が正しくありません。")
    if not maintenance_url.startswith("https://") or any(c in maintenance_url for c in ' "\\?#'):
        raise CloudflareError("メンテナンス画面のURLの設定が正しくありません。")
    query = urllib.parse.urlencode({"msg": clean_text(message), "until": clean_text(until, 40)}) + "&host="
    host_list = " ".join(_expression_string(host) for host in hosts)
    return {
        "ref": RULE_REF,
        "description": RULE_DESCRIPTION,
        "enabled": bool(enabled),
        "action": "redirect",
        "expression": f"(http.host in {{{host_list}}})",
        "action_parameters": {
            "from_value": {
                "target_url": {"expression": f'concat("{maintenance_url}?{query}", http.host)'},
                "status_code": 302,
                "preserve_query_string": False,
            }
        },
    }


class Settings:
    """/srv/rbs/cloudflare.env（setup が作る。root だけが読める）。"""

    KEYS = ("CF_API_TOKEN", "CF_ZONE_ID", "CF_RULESET_ID", "CF_RULE_ID", "CF_PUBLIC_HOSTS", "MAINTENANCE_URL")

    def __init__(self, values):
        self.values = values

    @classmethod
    def load(cls, path):
        values = {}
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        if any(not values.get(key) for key in cls.KEYS):
            return None
        return cls(values)

    @property
    def hosts(self):
        return [host for host in self.values["CF_PUBLIC_HOSTS"].split(",") if host.strip()]

    def client(self, opener=urllib.request.urlopen):
        return Client(self.values["CF_API_TOKEN"], self.values.get("CF_API_BASE", DEFAULT_BASE), opener=opener)

    def apply(self, enabled, message="", until="", opener=urllib.request.urlopen):
        rule = build_rule(
            hosts=self.hosts,
            maintenance_url=self.values["MAINTENANCE_URL"],
            enabled=enabled,
            message=message,
            until=until,
        )
        self.client(opener).update_rule(
            self.values["CF_ZONE_ID"], self.values["CF_RULESET_ID"], self.values["CF_RULE_ID"], rule
        )
