"""仕様を固めるための、決まったサンプルデータ。

書き出し（静的サイト）の結果を、毎回同じにするため、日付・順番・本文をすべて固定する。
新しい実装に書き換えるときも、同じデータを入れて、同じHTMLが出るかを比べる。
"""

from datetime import date, datetime, timezone
from unittest import mock

from main.models import Category, News, Pickup
from manuals.models import Manual
from video_archive.models import Video, VideoGroup

FROZEN_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def build_sample_data():
    with mock.patch("django.utils.timezone.now", return_value=FROZEN_NOW):
        news_category = Category.objects.create(name="お知らせ", order=1)
        event_category = Category.objects.create(name="大会", order=2)

        Pickup.objects.create(title="新入部員募集", caption="見学は随時", image="pickup/a.png", url="/about/", order=1)
        Pickup.objects.create(title="非公開のピックアップ", image="pickup/b.png", order=2, is_active=False)

        News.objects.create(title="公開のお知らせ", date=date(2026, 9, 30), category=news_category, caption="<p>公開の本文です。</p>")
        News.objects.create(title="部内限定の連絡", date=date(2026, 9, 29), category=event_category, caption="<p>部員だけの本文です。</p>", is_internal=True)
        News.objects.create(title="非公開の下書き", date=date(2026, 9, 28), caption="<p>出てはいけない本文</p>", is_active=False)
        News.objects.create(title="カテゴリなしの記事", date=date(2026, 9, 1), caption="")
        for number in range(1, 24):
            News.objects.create(title=f"記事{number:02d}", date=date(2026, 8, 1) + (date(2026, 8, 2) - date(2026, 8, 1)) * number, caption=f"<p>本文{number}</p>")

        Manual.objects.create(title="機材の使い方", content="# 見出し\n\n- 項目1\n- 項目2\n\n**太字**", order=1)
        Manual.objects.create(title="撮影の手順", content="手順です。", order=2)
        Manual.objects.create(title="非公開のマニュアル", content="出てはいけない", order=3, is_active=False)

        group = VideoGroup.objects.create(name="文化祭", order=1)
        Video.objects.create(
            title="文化祭2025", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", description="説明です。",
            group=group, event_date=date(2025, 9, 20), production_date=date(2025, 10, 1), order=1,
        )
        Video.objects.create(
            title="入学式2026", url="https://youtu.be/9bZkp7q19f0", has_subtitles=True, subtitle_language="日本語",
            event_date=date(2026, 4, 8), production_date=date(2026, 4, 20), order=1,
        )
        Video.objects.create(title="日付なしの動画", url="https://www.youtube.com/watch?v=3JZ_D3ELwOQ", event_date=None, production_date=None)
        Video.objects.create(
            title="非公開の動画", url="https://www.youtube.com/watch?v=L_jWHffIx5E", event_date=date(2026, 5, 1),
            production_date=date(2026, 5, 2), is_active=False,
        )
