"""公開サイト用サーバー（Apache・PHP）の自動更新。

毎週、決まった曜日・時刻を過ぎたら、「最新版にする」の依頼を1回だけ出す。
更新そのものは、手で押したときと同じ処理（失敗したら自動で元に戻る）。
管理画面（Django）は、ソースが変わるので、自動では更新しない。
"""

import json
from datetime import timedelta
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_FILE = "autoupdate.json"
WEEKDAY = 6  # 日曜
HOUR = 4  # 毎日3時のバックアップのあと


@dataclass
class State:
    enabled: bool = True
    last_slot: str = ""  # 最後に依頼を出した「更新の時刻」（例 2026-10-25T04:00）
    last_request: str = ""
    updated_by: str = ""

    @classmethod
    def load(cls, spool):
        try:
            data = json.loads((Path(spool) / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {key: data[key] for key in asdict(cls()) if key in data}
        if not isinstance(known.get("enabled", True), bool):
            known.pop("enabled")
        return cls(**known)

    def save(self, spool):
        from . import protocol

        protocol.write_json_atomic(Path(spool) / STATE_FILE, asdict(self), mode=0o644)


def latest_slot(moment):
    """いまから見て、いちばん最近の「更新の時刻」（毎週、日曜の4時）。"""
    days_back = (moment.weekday() - WEEKDAY) % 7
    slot = (moment - timedelta(days=days_back)).replace(hour=HOUR, minute=0, second=0, microsecond=0)
    return slot if slot <= moment else slot - timedelta(days=7)


def is_due(state, moment):
    """直近の更新の時刻を過ぎていて、その分の依頼をまだ出していなければ True。

    PCが止まっていて時刻を逃したときも、起動後に1回だけ出す（古い分は、まとめて1回）。
    """
    slot = latest_slot(moment).isoformat(timespec="minutes")
    return state.enabled and state.last_slot < slot


def read_state(spool):
    return State.load(spool)
