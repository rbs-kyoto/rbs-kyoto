"""「システムの状態」の各項目を確認する。

外部への問い合わせ（RDAP、endoflife.date）が失敗しても、その項目を
「確認できず」にするだけで、他の項目の確認は続ける。
"""

import platform
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import django
import requests
from django.conf import settings
from django.utils import timezone

from .models import Level, SystemStatus

TIMEOUT = 8
# これより古い結果は、ページを開いたときに確認し直す
MAX_AGE = timedelta(hours=24)
RDAP_URL = "https://rdap.org/domain/{domain}"
EOL_URL = "https://endoflife.date/api/{product}/{cycle}.json"

DOMAIN_WARNING_DAYS = 90
DOMAIN_DANGER_DAYS = 30
EOL_WARNING_DAYS = 180

ASK_SOMEONE = "詳しい人（OB・OGなど）に相談してください。"


def result(key, label, value, level, detail="", advice=""):
    return {
        "key": key,
        "label": label,
        "value": value,
        "level": level,
        "detail": detail,
        "advice": advice,
    }


def _days_until(day, today):
    return (day - today).days


def _parse_date(value):
    return date.fromisoformat(value[:10])


def _rdap_expiration(domain):
    """(状態, 期限) を返す。状態は "found"（期限あり）、"missing"（登録情報なし）、"no-date"（期限の公開なし）。"""
    response = requests.get(RDAP_URL.format(domain=domain), timeout=TIMEOUT)
    # 登録されていない名前（サブドメインなど）への答えは、.com は 404、.org は 400 と、レジストリごとに違う
    if response.status_code in (400, 404):
        return "missing", None
    response.raise_for_status()
    for event in response.json().get("events", []):
        if event.get("eventAction") == "expiration":
            return "found", _parse_date(event["eventDate"])
    return "no-date", None


def check_domain(host, today):
    """host がサブドメイン（poc-rbs.example.com など）のときは、登録情報のある親のドメインまでさかのぼって調べる。"""
    labels = host.lower().rstrip(".").split(".")
    # 長い順に、2つ以上のラベルが残るものまで（co.jp のような親は、本体が見つかった時点で調べない）
    candidates = [".".join(labels[start:]) for start in range(len(labels) - 1)] or [host]
    unknown = result(
        "domain", f"ドメイン（{host}）の期限", "—", Level.UNKNOWN, "期限を確認できませんでした。", "時間をおいて「今すぐ確認」を押してください。"
    )

    for domain in candidates:
        try:
            state, expires_on = _rdap_expiration(domain)
        except (requests.RequestException, ValueError, KeyError):
            return unknown
        if state == "missing":
            continue
        label = f"ドメイン（{domain}）の期限"
        if state == "no-date":
            return result(
                "domain", label, "—", Level.UNKNOWN,
                "このドメインは、登録情報に期限が公開されていません。",
                "ドメインの登録サービスの管理画面で、期限と自動更新の設定を確認してください。",
            )
        break
    else:
        return unknown

    note = f"{host} は {domain} のサブドメインなので、{domain} の期限を確認しました。" if domain != host else ""
    days = _days_until(expires_on, today)
    value = f"{expires_on:%Y年%-m月%-d日}（あと{days}日）" if days >= 0 else f"{expires_on:%Y年%-m月%-d日}（期限切れ）"
    advice = "ドメインの登録サービスで、更新手続き（または自動更新の設定）を確認してください。"
    if days <= DOMAIN_DANGER_DAYS:
        return result("domain", label, value, Level.DANGER, f"{note}期限が切れるとサイトが表示されなくなります。", advice)
    if days <= DOMAIN_WARNING_DAYS:
        return result("domain", label, value, Level.WARNING, f"{note}期限が近づいています。", advice)
    return result("domain", label, value, Level.OK, note)


def _os_release():
    try:
        lines = Path("/etc/os-release").read_text().splitlines()
    except OSError:
        return {}
    pairs = (line.split("=", 1) for line in lines if "=" in line)
    return {key: value.strip('"') for key, value in pairs}


def _php_version():
    php = shutil.which("php")
    if php is None:
        return None
    try:
        completed = subprocess.run(
            [php, "-r", "echo PHP_VERSION;"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def installed_software():
    """(キー, 表示名, endoflife.date の製品名, サイクル, インストール済みのバージョン) の一覧。"""
    software = []

    os_release = _os_release()
    if os_release.get("ID") in {"ubuntu", "debian"} and os_release.get("VERSION_ID"):
        software.append((
            "os",
            "OS",
            os_release["ID"],
            os_release["VERSION_ID"],
            os_release.get("PRETTY_NAME", os_release["VERSION_ID"]),
        ))

    python_version = platform.python_version()
    software.append(("python", "Python", "python", ".".join(python_version.split(".")[:2]), python_version))

    django_version = django.get_version()
    software.append(("django", "Django", "django", ".".join(django_version.split(".")[:2]), django_version))

    php_version = _php_version()
    if php_version:
        software.append(("php", "PHP", "php", ".".join(php_version.split(".")[:2]), php_version))

    return software


def _version_tuple(version):
    parts = []
    for part in version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_software(key, label, product, cycle, installed, today):
    label = f"{label}のサポート"
    try:
        response = requests.get(EOL_URL.format(product=product, cycle=cycle), timeout=TIMEOUT)
        response.raise_for_status()
        info = response.json()
        eol = info.get("eol")
    except (requests.RequestException, ValueError):
        return result(key, label, installed, Level.UNKNOWN, "サポート期限を確認できませんでした。")

    latest = info.get("latest")
    # apt で入れたもの（OS、PHP、Python）は番号を据え置いたまま修正が入るので、比べるのは pip で入れる Django だけ
    has_newer_patch = key == "django" and isinstance(latest, str) and _version_tuple(latest) > _version_tuple(installed)
    patch_note = f"新しい修正版 {latest} が出ています。" if has_newer_patch else ""

    if eol is True:
        return result(key, label, installed, Level.DANGER, "サポートが終了しています。" + patch_note, ASK_SOMEONE)
    if not isinstance(eol, str):
        level = Level.INFO if has_newer_patch else Level.OK
        return result(key, label, installed, level, ("サポート終了日は未定です。" + patch_note).strip())

    eol_on = _parse_date(eol)
    days = _days_until(eol_on, today)
    detail = f"{eol_on:%Y年%-m月%-d日}までサポートされます（あと{days}日）。" + patch_note
    if days < 0:
        return result(key, label, installed, Level.DANGER, f"{eol_on:%Y年%-m月%-d日}でサポートが終了しました。" + patch_note, ASK_SOMEONE)
    if days <= EOL_WARNING_DAYS:
        return result(key, label, installed, Level.WARNING, detail, "サポート終了までに、" + ASK_SOMEONE)
    if has_newer_patch:
        return result(key, label, installed, Level.INFO, detail, "セキュリティの修正が含まれていることがあるので、早めの更新をおすすめします。分からなければ、" + ASK_SOMEONE)
    return result(key, label, installed, Level.OK, detail)


def check_disk(path):
    label = "ディスクの空き容量"
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return result("disk", label, "—", Level.UNKNOWN, "空き容量を確認できませんでした。")

    free_ratio = usage.free / usage.total
    value = f"{usage.free / 1024 ** 3:.1f} GB（{free_ratio:.0%}）"
    advice = "古い画像や使わない動画のサムネイルを整理するか、" + ASK_SOMEONE
    if free_ratio < 0.1:
        return result("disk", label, value, Level.DANGER, "空きがほとんどありません。", advice)
    if free_ratio < 0.2:
        return result("disk", label, value, Level.WARNING, "空きが少なくなっています。", advice)
    return result("disk", label, value, Level.OK)


def check_uptime():
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return result("uptime", "起動してからの時間", "—", Level.UNKNOWN)
    booted_at = timezone.localtime() - timedelta(seconds=seconds)
    return result("uptime", "起動してからの時間", f"{int(seconds // 86400)}日", Level.INFO, f"{booted_at:%Y年%-m月%-d日 %H:%M}に起動しました。")


def check_publishing():
    from publisher import builder
    from publisher.models import Deployment

    label = "公開サイト"
    latest = Deployment.objects.first()
    active = builder.active_version()
    if latest is not None and latest.status == Deployment.Status.FAILED:
        return result(
            "publishing",
            label,
            f"バージョン {active} を公開中" if active else "未公開",
            Level.WARNING,
            f"最後のデプロイ（バージョン {latest.version}）が失敗しています。公開中のサイトはそのままです。",
            "「デプロイを管理」でエラー内容を確認して、直らなければ" + ASK_SOMEONE,
        )
    if active is None:
        return result("publishing", label, "未公開", Level.WARNING, "まだ一度もデプロイしていません。", "「デプロイを管理」からデプロイしてください。")
    return result("publishing", label, f"バージョン {active} を公開中", Level.OK)


def run_all(today=None):
    today = today or timezone.localdate()
    results = [check_domain(settings.CANONICAL_DOMAIN, today), check_publishing()]
    results += [check_software(*software, today=today) for software in installed_software()]
    results += [check_disk(settings.SITE_BUILD_ROOT if Path(settings.SITE_BUILD_ROOT).exists() else settings.BASE_DIR), check_uptime()]
    return results


def refresh():
    status = SystemStatus.get_solo()
    status.results = run_all()
    status.checked_at = timezone.now()
    status.save(update_fields=["results", "checked_at"])
    return status


def refresh_if_stale():
    status = SystemStatus.get_solo()
    if status.checked_at is None or timezone.now() - status.checked_at > MAX_AGE:
        return refresh()
    return status
