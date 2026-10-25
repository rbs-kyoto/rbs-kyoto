#!/usr/bin/env python3
"""Cloudflare のメンテナンス画面を、自動でセットアップする。

やること（何度実行しても壊れない）:
  1. API トークンで、サイトのゾーンを探す
  2. メンテナンス画面（固定ページ）を、Workers の静的配信にデプロイする（wrangler は Docker の中で動かすので、Node.js は要らない）
  3. 公開サイトをその画面へ飛ばす「リダイレクトルール」を、無効の状態で1つ足す（ほかのルールには触れない）
  4. 本当に切り替えられるか、試しに1回更新してみる（権限が足りなければ、ここで分かる）
  5. opsd 用の設定ファイル（<RBS_HOME>/cloudflare.env、root だけが読める）を作る

最初に手でやるのは、API トークンを1つ発行することだけ（README.md を参照）。標準ライブラリだけで動く。
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent))

from opsd import cloudflare  # noqa: E402

PAGE_DIR = ROOT / "maintenance-page"
WRANGLER_IMAGE = "node:22-slim"
WRANGLER_PACKAGE = "wrangler@4"
SUBDOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,60}[a-z0-9]")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,50}[a-z0-9]")

TOKEN_HELP = """\
Cloudflare の API トークンが必要です（最初の1回だけ、手で作ります）。

  ダッシュボード右上のアイコン → プロフィール → API トークン → トークンを作成 → 「カスタム トークン」
    権限（3つ）
      アカウント ／ Workers スクリプト ／ 編集
      ゾーン     ／ Single Redirect（または Dynamic URL Redirects） ／ 編集
      ゾーン     ／ ゾーン ／ 読み取り
    リソース
      アカウント：自分のアカウント　／　ゾーン：このサイトのゾーンだけ
"""


class SetupError(Exception):
    pass


def say(text=""):
    print(text, flush=True)


def read_env_file(path):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def deploy_page(*, token, account_id, name, hosts, runner, workdir=None):
    """固定ページを Workers にデプロイする（wrangler を Docker で動かす）。"""
    work = Path(workdir or tempfile.mkdtemp(prefix="rbs-maintenance-"))
    try:
        shutil.copytree(PAGE_DIR, work / "page", dirs_exist_ok=True)
        page = work / "page"
        (page / "public" / "config.json").write_text(json.dumps({"allowedHosts": hosts}, ensure_ascii=False), encoding="utf-8")
        config = (page / "wrangler.jsonc").read_text(encoding="utf-8")
        (page / "wrangler.jsonc").write_text(config.replace('"name": "rbs-maintenance"', f'"name": "{name}"', 1), encoding="utf-8")

        # トークンはコマンドの引数に出さず、環境変数で渡す（ps で見えてしまうため）
        env = {**os.environ, "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": account_id}
        command = [
            "docker", "run", "--rm", "-v", f"{page}:/work", "-w", "/work",
            "-e", "CLOUDFLARE_API_TOKEN", "-e", "CLOUDFLARE_ACCOUNT_ID",
            WRANGLER_IMAGE, "npx", "--yes", WRANGLER_PACKAGE, "deploy",
        ]
        completed = runner(command, env=env, capture_output=True, text=True)
        if completed.returncode != 0:
            tail = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-12:])
            raise SetupError(f"メンテナンス画面のデプロイに失敗しました。\n{tail}")
    finally:
        if workdir is None:
            shutil.rmtree(work, ignore_errors=True)


def ensure_rule(client, zone_id, hosts, maintenance_url):
    """リダイレクトルールを、無効の状態で用意する。すでにあれば、有効・無効はそのまま、設定だけ最新にする。

    戻り値は (ルールセットのID, ルールのID, いま有効か)。
    """
    entry = client.entrypoint(zone_id)
    if entry is None:
        rule = cloudflare.build_rule(hosts=hosts, maintenance_url=maintenance_url, enabled=False)
        created = client.create_entrypoint(zone_id, rule)
        return created["id"], _rule_id(created, "ルールを作れませんでした。"), False

    existing = next((rule for rule in entry.get("rules", []) if rule.get("ref") == cloudflare.RULE_REF), None)
    if existing is None:
        rule = cloudflare.build_rule(hosts=hosts, maintenance_url=maintenance_url, enabled=False)
        updated = client.add_rule(zone_id, entry["id"], rule)
        return entry["id"], _rule_id(updated, "ルールを追加できませんでした。"), False

    enabled = bool(existing.get("enabled", False))
    rule = cloudflare.build_rule(hosts=hosts, maintenance_url=maintenance_url, enabled=enabled)
    client.update_rule(zone_id, entry["id"], existing["id"], rule)
    return entry["id"], existing["id"], enabled


def _rule_id(ruleset, error):
    for rule in (ruleset or {}).get("rules", []):
        if rule.get("ref") == cloudflare.RULE_REF:
            return rule["id"]
    raise SetupError(error)


def write_settings(path, values):
    """root だけが読めるファイルとして、一度に書き込む（途中の状態を残さない）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write("# rbs京都: Cloudflare のメンテナンス画面の設定（setup.sh が作る。人に見せない）\n")
        file.writelines(f"{key}={value}\n" for key, value in values.items())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def check_page(url, attempts=5, opener=urllib.request.urlopen, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": cloudflare.USER_AGENT}), timeout=15) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        sleep(3)
    return False


def run_setup(args, *, runner=subprocess.run, ask=input, ask_secret=getpass.getpass, opener=urllib.request.urlopen, sleep=time.sleep):
    home = Path(args.home)
    env_file = read_env_file(home / ".env")
    saved = read_env_file(home / "cloudflare.env")

    hosts = [h.strip().lower() for h in (args.hosts or env_file.get("PUBLIC_HOST", "")).split(",") if h.strip()]
    if not hosts:
        raise SetupError(f"公開サイトのホスト名が分かりません。{home}/.env の PUBLIC_HOST か、--hosts で指定してください。")
    name = args.worker_name
    if not NAME_RE.fullmatch(name):
        raise SetupError("--worker-name は、英小文字・数字・ハイフンだけにしてください。")

    token = os.environ.get("CF_API_TOKEN") or (saved.get("CF_API_TOKEN") if args.reuse_token else "")
    if not token:
        say(TOKEN_HELP)
        token = ask_secret("API トークン（入力しても表示されません）: ").strip()
    if not token:
        raise SetupError("API トークンが入力されませんでした。")

    api_base = os.environ.get("CF_API_BASE") or saved.get("CF_API_BASE") or cloudflare.DEFAULT_BASE
    client = cloudflare.Client(token, api_base, opener=opener)

    say("== 1/5 ゾーンの確認")
    zones = [client.find_zone(host) for host in hosts]
    if len({zone["id"] for zone in zones}) != 1:
        raise SetupError("指定したホスト名が、別々のゾーンにあります。1つのゾーンのホスト名だけを指定してください。")
    zone = zones[0]
    say(f"ゾーン {zone['name']} が見つかりました。対象のホスト: {', '.join(hosts)}")

    say("== 2/5 メンテナンス画面のデプロイ（初回は数分かかります）")
    subdomain = client.workers_subdomain(zone["account_id"])
    if not subdomain:
        say("このアカウントの workers.dev のサブドメインが、まだありません。メンテナンス画面のURLの一部になります。")
        subdomain = ask("決めてください（英小文字・数字・ハイフン、例: rbs-kyoto）: ").strip().lower()
        if not SUBDOMAIN_RE.fullmatch(subdomain):
            raise SetupError("サブドメインは、英小文字・数字・ハイフンだけの、2〜62文字にしてください。")
        subdomain = client.set_workers_subdomain(zone["account_id"], subdomain)
    maintenance_url = f"https://{name}.{subdomain}.workers.dev/"
    deploy_page(token=token, account_id=zone["account_id"], name=name, hosts=hosts, runner=runner)
    say(f"デプロイしました: {maintenance_url}")
    if check_page(maintenance_url, opener=opener, sleep=sleep):
        say("メンテナンス画面が表示できることを確認しました。")
    else:
        say("※ メンテナンス画面をまだ開けませんでした。反映に数分かかることがあります。あとで上のURLを開いて確かめてください。")

    say("== 3/5 リダイレクトルール（無効の状態で用意します。ほかのルールには触れません）")
    ruleset_id, rule_id, enabled = ensure_rule(client, zone["id"], hosts, maintenance_url)

    say("== 4/5 切り替えの権限を確認")
    # いまの状態のまま更新する（メンテナンス中に再実行しても、勝手に終わらせない）
    rule = cloudflare.build_rule(hosts=hosts, maintenance_url=maintenance_url, enabled=enabled)
    try:
        client.update_rule(zone["id"], ruleset_id, rule_id, rule)
    except cloudflare.CloudflareError as error:
        raise SetupError(
            f"ルールを更新できませんでした: {error}\n"
            "トークンに、ゾーンの「Single Redirect（Dynamic URL Redirects）」の編集権限があるか確認してください。"
        ) from error
    say("ルールを更新できることを確認しました" + ("（メンテナンス中の状態は、そのままです）。" if enabled else "（まだ無効のままです）。"))

    say("== 5/5 設定ファイルの作成")
    values = {
        "CF_API_TOKEN": token,
        "CF_ZONE_ID": zone["id"],
        "CF_RULESET_ID": ruleset_id,
        "CF_RULE_ID": rule_id,
        "CF_PUBLIC_HOSTS": ",".join(hosts),
        "MAINTENANCE_URL": maintenance_url,
    }
    if api_base != cloudflare.DEFAULT_BASE:
        values["CF_API_BASE"] = api_base
    settings_path = home / "cloudflare.env"
    write_settings(settings_path, values)
    say(f"{settings_path} を作りました（root だけが読めます）。")

    if Path("/run/systemd/system").is_dir() and not args.no_restart:
        subprocess_result = runner(["systemctl", "restart", "rbs-opsd"], capture_output=True, text=True)
        say("operator（rbs-opsd）を再起動しました。" if subprocess_result.returncode == 0 else "※ operator の再起動に失敗しました: sudo systemctl restart rbs-opsd")
    else:
        say("operator を、再起動してください（設定は、次に起動したときに読まれます）。")

    say()
    say("できました。メンテナンス画面は、管理画面の「システムの操作」か、救出画面から、切り替えられます。")
    say("設定 → メンテナンス で決めた予定も、自動で反映されます。")
    say()
    say("※ このトークンは、このPCの設定ファイル以外には残していません。使わなくなったら、Cloudflare で削除してください。")


def main(argv=None, **kwargs):
    parser = argparse.ArgumentParser(description="Cloudflare のメンテナンス画面を、自動でセットアップする")
    parser.add_argument("--home", default=os.environ.get("RBS_HOME", "/srv/rbs"), help="rbs の置き場所（既定 /srv/rbs）")
    parser.add_argument("--hosts", default="", help="メンテナンス画面に切り替える公開サイトのホスト名（コンマ区切り。既定は .env の PUBLIC_HOST）")
    parser.add_argument("--worker-name", default="rbs-maintenance", help="Workers の名前")
    parser.add_argument("--reuse-token", action="store_true", help="すでにある cloudflare.env のトークンを使う")
    parser.add_argument("--no-restart", action="store_true", help="operator を再起動しない")
    args = parser.parse_args(argv)
    try:
        run_setup(args, **kwargs)
    except (SetupError, cloudflare.CloudflareError) as error:
        print(f"\nエラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
