"""メンテナンス設定を保存したら、予定を operator（opsd）に渡す。

公開サイトの切り替えは、Cloudflare のルールで opsd が行う。予定の時刻の判定も opsd がするので、
Django が止まっていても、予定どおりに始まって終わる。ここでは「いまの設定」を渡すだけ。
operator と繋がっていない環境（OPS_SPOOL が未設定）では、何もしない。
"""

import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from opsd import protocol

logger = logging.getLogger(__name__)


def _iso(value):
    return timezone.localtime(value).isoformat(timespec="seconds") if value else ""


def schedule_params(setting):
    return {
        "mode": setting.mode,
        "starts_at": _iso(setting.starts_at),
        "resume_at": _iso(setting.resume_at),
        "auto_resume_at": _iso(setting.auto_resume_at),
        "recovery_in_progress": bool(setting.recovery_in_progress),
        "announcement": (setting.announcement or "")[: protocol.MAX_ANNOUNCEMENT_LENGTH],
    }


def send_schedule(sender, instance, raw=False, **kwargs):
    spool = settings.OPS_SPOOL
    if raw or not spool or not Path(spool).is_dir():
        return
    try:
        protocol.submit(spool, "maintenance_set", schedule_params(instance), source="django:maintenance")
    except (OSError, ValueError):
        logger.exception("Could not hand the maintenance schedule to the operator")
