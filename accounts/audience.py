"""利用者の立場(校外・部外・部内)を判定する共通関数。

サイト全体で「誰に見せてよいか」を決めるときは、is_staff などを直接見ずに、
必ずここの関数を使う。立場の決め方を変えたくなったら、このファイルだけ直せばよい。

    校外 (PUBLIC) : ログインしていない人。インターネット上の誰でも。
    部外 (SCHOOL) : ログインしているが、放送部員ではない人。
    部内 (CLUB)   : 放送部員。名簿(roll)でアカウントが連携され、
                    「放送部員」にチェックが付いている人。スーパーユーザーも含む。

部内のうち、編集までできる人を「編集担当」と呼ぶ(is_club_editor)。
部員であり、かつスタッフ権限(is_staff)を持つ人のこと。
スタッフ権限だけあっても、部員でなければ何も編集できない。
"""

from django.db import models


class Audience(models.TextChoices):
    PUBLIC = "public", "校外(誰でも)"
    SCHOOL = "school", "部外(ログインした人)"
    CLUB = "club", "部内(放送部員)"


def audience_of(user):
    """user の立場を Audience で返す。同じリクエスト内では結果を使い回す。"""
    if user is None or not user.is_authenticated or not user.is_active:
        return Audience.PUBLIC

    cached = getattr(user, "_audience_cache", None)
    if cached is not None:
        return cached

    if user.is_superuser:
        audience = Audience.CLUB
    else:
        # 名簿と連携していないアカウントは roster_entry を持たない
        entry = getattr(user, "roster_entry", None)
        audience = (
            Audience.CLUB if entry is not None and entry.is_member else Audience.SCHOOL
        )
    user._audience_cache = audience
    return audience


def is_outside_school(user):
    """校外(ログインしていない人)か。"""
    return audience_of(user) == Audience.PUBLIC


def is_school_non_member(user):
    """部外(ログインしているが放送部員ではない人)か。"""
    return audience_of(user) == Audience.SCHOOL


def is_club_member(user):
    """部内(放送部員)か。"""
    return audience_of(user) == Audience.CLUB


def is_club_editor(user):
    """部内の編集担当か(部員で、スタッフ権限を持つ人。スーパーユーザーも含む)。"""
    return is_club_member(user) and (user.is_staff or user.is_superuser)


def visible_audiences(user):
    """user が見てよい公開範囲の一覧。ニュースなどの絞り込みに使う。

    校外の人は「校外」向けだけ、部外の人は「校外・部外」向け、
    部内の人はすべて見られる。
    """
    audience = audience_of(user)
    if audience == Audience.CLUB:
        return [Audience.PUBLIC, Audience.SCHOOL, Audience.CLUB]
    if audience == Audience.SCHOOL:
        return [Audience.PUBLIC, Audience.SCHOOL]
    return [Audience.PUBLIC]


def can_view(user, visibility):
    """公開範囲 visibility のものを、user が見てよいか。"""
    return visibility in visible_audiences(user)
