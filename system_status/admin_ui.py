"""管理画面（Unfold）のヘッダーとサイドバーに出す表示。

ここでは保存済みの結果を読むだけで、外部への問い合わせはしない。
"""

from publisher import builder

from .models import Level, SystemStatus


def _status():
    return SystemStatus.objects.filter(pk=1).first()


def environment_callback(request):
    # 画面右上に常に出るラベル。どの画面にいても気づけるようにする
    status = _status()
    if status is not None and status.count(Level.DANGER):
        return ["要対応あり", "danger"]
    if builder.has_unpublished_changes():
        return ["未公開の変更あり", "warning"]
    if status is not None and status.count(Level.WARNING):
        return ["注意あり", "warning"]
    return None


def attention_badge(request):
    status = _status()
    count = status.count(Level.DANGER, Level.WARNING) if status is not None else 0
    return count or None
