"""操作ボタン・救出画面と operator（opsd）の取り決め。

管理画面（Django）も救出画面（PHP）も、サーバーを直接は操作しない。
spool/requests/ に「依頼」のJSONを置き、operator が実行して
spool/results/ に結果を書く。operator は ACTIONS にある種類だけを、
ここで検証した引数でしか実行しない。

標準ライブラリだけで動く（Django からも operator からも読み込む）。
"""

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

REQUEST_ID_RE = re.compile(r"\d{14}-[0-9a-f]{8}")
BACKUP_ID_RE = re.compile(r"\d{8}-\d{6}-[a-z]+(?:-[a-z]+)*")
LABEL_RE = re.compile(r"[a-z]+(?:-[a-z]+)*")

RESTARTABLE_SERVICES = ("admin", "web")
LOG_SERVICES = ("admin", "web", "opsd")
DEFAULT_LOG_LINES = 200
MAX_LOG_LINES = 1000

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
FINISHED = (SUCCEEDED, FAILED)

# 画面に出す名前と説明。params は後で validate() が見る。
ACTIONS = {
    "backup": {
        "label": "バックアップを取る",
        "description": "データ（DBと画像）を今の状態で保存します。",
    },
    "update_web": {
        "label": "公開サイト（Apache・PHP）を更新",
        "description": "最新のコードとセキュリティ修正を取り込んで作り直します。失敗したら自動で元に戻ります。",
    },
    "update_admin": {
        "label": "管理画面（Django）を更新",
        "description": "更新前にバックアップを取り、新しい版に入れ替えます。1〜2分ほど管理画面が使えなくなります。失敗したら自動で元に戻ります。",
    },
    "restart": {
        "label": "再起動",
        "description": "指定したものを再起動します。",
    },
    "logs": {
        "label": "ログを見る",
        "description": "直近のログを表示します。",
    },
    "restore": {
        "label": "バックアップから復元",
        "description": "データと管理画面の版を、そのバックアップを取った時点に戻します。",
    },
    "rollback": {
        "label": "更新前の状態に戻す",
        "description": "直近の「更新前」のバックアップに、データと管理画面の版を戻します。",
    },
}

# 救出画面（PHP）から受け付ける種類。Django 側の操作ボタンは全部使える。
RESCUE_ACTIONS = ("backup", "restart", "logs", "restore", "rollback")


def validate(action, params):
    """検証済みの引数を返す。不正なら ValueError。"""
    if action not in ACTIONS:
        raise ValueError(f"未対応の操作です: {action!r}")
    params = params or {}
    if not isinstance(params, dict):
        raise ValueError("引数の形式が正しくありません。")

    if action == "restart":
        service = params.get("service")
        if service not in RESTARTABLE_SERVICES:
            raise ValueError("再起動できるのは admin と web だけです。")
        return {"service": service}

    if action == "logs":
        service = params.get("service")
        if service not in LOG_SERVICES:
            raise ValueError("ログを見られるのは admin・web・opsd だけです。")
        lines = params.get("lines", DEFAULT_LOG_LINES)
        if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= MAX_LOG_LINES:
            raise ValueError(f"行数は1〜{MAX_LOG_LINES}で指定してください。")
        return {"service": service, "lines": lines}

    if action == "restore":
        backup = params.get("backup")
        if not isinstance(backup, str) or not BACKUP_ID_RE.fullmatch(backup):
            raise ValueError("バックアップの指定が正しくありません。")
        return {"backup": backup}

    return {}


def new_request_id(now=None):
    return f"{(now or datetime.now()):%Y%m%d%H%M%S}-{secrets.token_hex(4)}"


def write_json_atomic(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def submit(spool, action, params=None, source="unknown", now=None):
    """依頼を書いて、依頼IDを返す。"""
    params = validate(action, params)
    request_id = new_request_id(now)
    write_json_atomic(
        Path(spool) / "requests" / f"{request_id}.json",
        {
            "id": request_id,
            "action": action,
            "params": params,
            "source": str(source)[:100],
            "requested_at": (now or datetime.now()).isoformat(timespec="seconds"),
        },
        mode=0o666,
    )
    return request_id


def read_status(spool, request_id):
    """依頼の今の状態。結果があればそれ、なければ待機中、依頼自体がなければ None。"""
    if not REQUEST_ID_RE.fullmatch(str(request_id)):
        return None
    spool = Path(spool)
    result = _read_json(spool / "results" / f"{request_id}.json")
    if result is not None:
        return result
    request = _read_json(spool / "requests" / f"{request_id}.json")
    if request is not None:
        return {**request, "status": QUEUED, "output": ""}
    return None


def list_recent(spool, limit=10):
    """結果と待機中の依頼を新しい順に。"""
    spool = Path(spool)
    ids = {path.stem for path in (spool / "results").glob("*.json") if not path.name.startswith(".")}
    ids |= {path.stem for path in (spool / "requests").glob("*.json") if not path.name.startswith(".")}
    statuses = (read_status(spool, request_id) for request_id in sorted(ids, reverse=True)[:limit])
    return [status for status in statuses if status is not None]


def list_backups(backups_dir):
    """バックアップのメタ情報を新しい順に。"""
    backups_dir = Path(backups_dir)
    if not backups_dir.is_dir():
        return []
    backups = []
    for directory in backups_dir.iterdir():
        if not BACKUP_ID_RE.fullmatch(directory.name):
            continue
        meta = _read_json(directory / "meta.json")
        if meta is not None and meta.get("id") == directory.name:
            backups.append(meta)
    return sorted(backups, key=lambda meta: meta["id"], reverse=True)
