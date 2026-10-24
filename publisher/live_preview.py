"""編集画面のリアルタイムプレビュー。

保存していない入力内容でモデルのインスタンスを作り、そのデータが表示される
ページを描画する。DBには書き込まない。
"""

from main.models import News, Pickup
from main.sanitizers import sanitize_richtext
from manuals.models import Manual
from video_archive.models import Video

from .pages import MEMBERS, PUBLIC, Page, iter_pages

# 画像は送らず、ブラウザ側でこの目印を選択中のファイルに差し替える
INLINE_FILE_PREFIX = "live-preview-file:"


class InlineFile:
    """テンプレートの {{ obj.image.url }} に目印を返すための代わりのファイル。"""

    def __init__(self, field_name):
        self.url = f"{INLINE_FILE_PREFIX}{field_name}"

    def __bool__(self):
        return True


def _news(news):
    # 本文は保存時に許可リストで消毒しているので、プレビューでも同じにする
    news.caption = sanitize_richtext(news.caption)
    variant = MEMBERS if news.is_internal else PUBLIC
    location = "ニュース記事のページ（部員限定）" if news.is_internal else "ニュース記事のページ"
    return Page(f"/news/{news.pk or 'new'}/", "main/news_detail.html", {"news": news}), variant, location


def _pickup(pickup):
    index = next(page for page in iter_pages(PUBLIC) if page.path == "/")
    pickups = [item for item in index.context["pickups"] if item.pk != pickup.pk]
    # 編集中のものを先頭にして、スライドの最初に表示する
    if pickup.is_active and pickup.image:
        pickups.insert(0, pickup)
    location = "トップページのスライド（先頭に表示中）" if pickup.is_active else "トップページ（非公開のため表示されません）"
    return Page("/", "main/index.html", {**index.context, "pickups": pickups}), PUBLIC, location


def _manual(manual):
    return (
        Page(f"/manuals/{manual.pk or 'new'}/", "manuals/manual_detail.html", {"manual": manual}),
        MEMBERS,
        "マニュアルのページ（部員限定）",
    )


def _video(video):
    return (
        Page(f"/videos/{video.pk or 'new'}/", "video_archive/video_detail.html", {"video": video, "return_year": None}),
        MEMBERS,
        "動画のページ（部員限定）",
    )


PREVIEWS = {
    News: _news,
    Pickup: _pickup,
    Manual: _manual,
    Video: _video,
}


def build(instance):
    """(Page, variant, 表示場所の説明) を返す。"""
    page, variant, location = PREVIEWS[type(instance)](instance)
    if not isinstance(instance, Pickup) and not instance.is_active:
        location += "・非公開のため書き出されません"
    return page, variant, location
