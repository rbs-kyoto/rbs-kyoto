"""ビューに付ける、立場ごとの入場制限。判定そのものは accounts.audience にある。

    school_required      : 部外・部内(ログインしていれば誰でも)
    club_member_required : 部内(放送部員)のみ
    club_editor_required : 編集担当(スーパーユーザー)のみ

校外(未ログイン)でも見せてよいページには、何も付けない。
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .audience import is_club_editor, is_club_member

school_required = login_required


def _require(check):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


# 未ログインはログイン画面へ、ログイン済みで条件を満たさない人は403にする。
club_member_required = _require(is_club_member)
club_editor_required = _require(is_club_editor)
