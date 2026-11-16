"""パスワードの総当たりを防ぐ、失敗回数の制限。

同じ相手(アカウント)に対する失敗が、1時間に5回たまると、それ以上は試せなくなる。
記録はDBに置くので、ログインし直したりCookieを消したりしても解除されない。
"""

from datetime import timedelta

from django.utils import timezone

from .models import FailedAttempt

MAX_FAILURES = 5
WINDOW = timedelta(hours=1)


def _normalize(key):
    return str(key).strip().casefold()[:150]


def _recent(kind, key):
    return FailedAttempt.objects.filter(
        kind=kind,
        key=_normalize(key),
        attempted_at__gt=timezone.now() - WINDOW,
    )


def is_blocked(kind, key):
    """いま試行を止めるべきか(直近1時間の失敗が上限に達しているか)。"""
    return _recent(kind, key).count() >= MAX_FAILURES


def record_failure(kind, key):
    """失敗を1回記録する。ついでに、期限が切れた古い記録を掃除する。"""
    FailedAttempt.objects.filter(attempted_at__lte=timezone.now() - WINDOW).delete()
    FailedAttempt.objects.create(kind=kind, key=_normalize(key))


def clear(kind, key):
    """成功したときに、それまでの失敗の記録を消す。"""
    FailedAttempt.objects.filter(kind=kind, key=_normalize(key)).delete()
