"""テスト用の補助関数。"""

from roll.models import RosterEntry


def make_member(user, name=None):
    """user を放送部員(部内)にする。名簿に連携し、「放送部員」にチェックを付ける。"""
    return RosterEntry.objects.create(
        name=name or user.username,
        is_member=True,
        account=user,
    )
