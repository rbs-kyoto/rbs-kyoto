"""メンテナンスの予定と、Cloudflare に反映した状態。

予定（Schedule）は Django の「メンテナンス設定」と同じ考え方で、時刻から「メンテナンス中か」を決める。
opsd が持つので、Django が止まっていても、予定どおりに始まり、予定どおりに終わる。
状態は spool/maintenance.json に書く（管理画面・救出画面が読む。書くのは opsd だけ）。
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import protocol

STATE_FILE = "maintenance.json"
INACTIVE, ACTIVE, RECOVERY = "inactive", "active", "recovery"
RETRY_SECONDS = 30
RECOVERY_NOTICE = "復旧作業を続けています。"


def parse_time(value):
    """ISO形式の日時（時差なしなら、このPCの時刻）。空なら None。"""
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment.astimezone() if moment.tzinfo is None else moment


@dataclass
class Schedule:
    mode: str = "off"
    starts_at: str = ""
    resume_at: str = ""
    auto_resume_at: str = ""
    recovery_in_progress: bool = False
    announcement: str = ""

    @classmethod
    def from_params(cls, params):
        return cls(**protocol.validate("maintenance_set", params))

    def status_at(self, now):
        """Django の MaintenanceSetting.status_at と同じ判定。"""
        now = now.astimezone() if now.tzinfo is None else now
        starts_at, auto_resume_at = parse_time(self.starts_at), parse_time(self.auto_resume_at)
        if self.mode == "off":
            return INACTIVE
        if self.mode == "emergency":
            return RECOVERY if self.recovery_in_progress else ACTIVE
        if starts_at is None or now < starts_at:
            return INACTIVE
        if auto_resume_at is not None and now >= auto_resume_at:
            return RECOVERY if self.recovery_in_progress else INACTIVE
        return ACTIVE

    def wanted(self, now):
        """(メンテナンス画面にするか, 画面に出すお知らせ, 再開予定)"""
        status = self.status_at(now)
        if status == INACTIVE:
            return False, "", ""
        message = " ".join(self.announcement.split())
        if status == RECOVERY and not message:
            message = RECOVERY_NOTICE
        resume = parse_time(self.resume_at)
        return True, message, f"{resume:%Y-%m-%d %H:%M}" if resume else ""


@dataclass
class State:
    schedule: Schedule = field(default_factory=Schedule)
    applied: "dict | None" = None  # {"enabled", "message", "until", "at"}
    configured: bool = True
    last_error: str = ""
    next_retry: str = ""
    updated_at: str = ""
    updated_by: str = ""

    def to_json(self):
        data = asdict(self)
        return data

    @classmethod
    def load(cls, spool):
        try:
            data = json.loads((Path(spool) / STATE_FILE).read_text(encoding="utf-8"))
            schedule = Schedule(**{**asdict(Schedule()), **data.get("schedule", {})})
            return cls(
                schedule=schedule,
                applied=data.get("applied"),
                configured=data.get("configured", True),
                last_error=data.get("last_error", ""),
                next_retry=data.get("next_retry", ""),
                updated_at=data.get("updated_at", ""),
                updated_by=data.get("updated_by", ""),
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, spool):
        protocol.write_json_atomic(Path(spool) / STATE_FILE, self.to_json())


def read_state(spool):
    """管理画面・救出画面向けに、状態を辞書で返す（ファイルがなければ None）。"""
    try:
        return json.loads((Path(spool) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
