"""静的書き出しの対象ページ一覧。

各ビューの絞り込みを「スタッフではない閲覧者」として再現する。編集リンクや
非公開データは書き出さない（編集は管理ホストで行う）。

クエリ付きのページ（?page=2 など）は QUERY_KEYS の順で
<パス>/_q/<key>-<value>/index.html に書き出す。gate/ も同じ規則で探す。
"""

import re
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

from django.core.paginator import Paginator
from django.urls import reverse

from main.models import News, Pickup
from main.views import APPS
from manuals.models import Manual
from manuals.views import DEFAULT_SORT, SORT_OPTIONS
from video_archive.models import Video
from video_archive.utils import format_fiscal_year

# 管理ホストで動いていても、書き出すページのリンクは公開サイトのURLで解決する
PUBLIC_URLCONF = "config.urls"

PUBLIC = "public"
MEMBERS = "members"
VARIANTS = (PUBLIC, MEMBERS)

QUERY_KEYS = ("sort", "page", "year")
QUERY_VALUE_RE = re.compile(r"[a-z0-9]{1,16}")

# マイページで gate/ がログイン中のメールアドレスに置き換える目印
EMAIL_PLACEHOLDER = "<!--RBS_GATE_EMAIL-->"
# ログイン画面で gate/ がエラーメッセージに置き換える目印
MESSAGE_PLACEHOLDER = "<!--RBS_GATE_MESSAGE-->"

ERROR_CODES = (400, 403, 404, 500)

_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


@dataclass(frozen=True)
class Page:
    path: str
    template: str
    context: dict = field(default_factory=dict, hash=False, compare=False)
    query: tuple = ()

    @property
    def file_path(self):
        return page_file_path(self.path, dict(self.query))


def query_suffix(query):
    parts = []
    for key in QUERY_KEYS:
        value = str(query.get(key, ""))
        if QUERY_VALUE_RE.fullmatch(value):
            parts.append(f"{key}-{value}")
    return "/".join(parts)


def page_file_path(path, query=None):
    directory = path.strip("/")
    suffix = query_suffix(query or {})
    if suffix:
        directory = f"{directory}/_q/{suffix}" if directory else f"_q/{suffix}"
    return f"{directory}/index.html" if directory else "index.html"


def viewer_for(variant):
    is_member = variant == MEMBERS
    return SimpleNamespace(
        is_authenticated=is_member,
        is_staff=False,
        is_superuser=False,
    )


def _visible_news(variant):
    news = News.objects.filter(is_active=True)
    if variant == PUBLIC:
        news = news.filter(is_internal=False)
    return news.select_related("category").order_by("-date")


def iter_pages(variant):
    yield from _main_pages(variant)
    yield from _account_pages(variant)
    if variant == MEMBERS:
        yield from _manual_pages()
        yield from _video_pages()


def _main_pages(variant):
    news = _visible_news(variant)
    yield Page(
        "/",
        "main/index.html",
        {
            "pickups": Pickup.objects.filter(is_active=True),
            "news": news[:5],
            "apps": [{**app, "url": reverse(app["url_name"], urlconf=PUBLIC_URLCONF)} for app in APPS],
        },
    )
    yield Page("/about/", "main/about.html")

    paginator = Paginator(news, 20)
    for number in paginator.page_range:
        page_obj = paginator.page(number)
        yield Page(
            "/news/",
            "main/news_all.html",
            {"news_list": page_obj, "page_obj": page_obj},
            query=(("page", str(number)),) if number > 1 else (),
        )

    for item in news:
        yield Page(f"/news/{item.pk}/", "main/news_detail.html", {"news": item})


def _account_pages(variant):
    if variant == PUBLIC:
        yield Page("/accounts/login/", "publisher/site/login.html", {"message_placeholder": MESSAGE_PLACEHOLDER})
    else:
        yield Page("/accounts/mypage/", "publisher/site/mypage.html", {"email_placeholder": EMAIL_PLACEHOLDER})


def _manual_pages():
    manuals = Manual.objects.filter(is_active=True)
    yield Page("/manuals/", "manuals/manual_list.html", {"manuals": manuals, "sort": DEFAULT_SORT})
    for sort in (DEFAULT_SORT, *SORT_OPTIONS):
        ordered = manuals.order_by(SORT_OPTIONS[sort]) if sort in SORT_OPTIONS else manuals
        yield Page(
            "/manuals/",
            "manuals/manual_list.html",
            {"manuals": ordered, "sort": sort},
            query=(("sort", sort),),
        )
    for manual in manuals:
        yield Page(f"/manuals/{manual.pk}/", "manuals/manual_detail.html", {"manual": manual})


def _fiscal_year(day):
    return day.year - (day.month < 4)


def _video_pages():
    videos = list(Video.objects.filter(is_active=True).select_related("group"))

    fiscal_year_counts = {}
    undated_videos = []
    for video in videos:
        if video.event_date is None:
            undated_videos.append(video)
            continue
        year = _fiscal_year(video.event_date)
        fiscal_year_counts[year] = fiscal_year_counts.get(year, 0) + 1

    yield Page(
        "/videos/",
        "video_archive/video_list.html",
        {
            "fiscal_years": [
                {
                    "year": year,
                    "label": format_fiscal_year(year),
                    "count": str(fiscal_year_counts[year]).translate(_FULLWIDTH_DIGITS),
                }
                for year in sorted(fiscal_year_counts, reverse=True)
            ],
            "undated_videos": undated_videos,
        },
    )

    for year in fiscal_year_counts:
        year_videos = (
            Video.objects.filter(
                is_active=True,
                event_date__gte=date(year, 4, 1),
                event_date__lt=date(year + 1, 4, 1),
            )
            .select_related("group")
            .order_by("group__order", "group__name", "order", "-registered_at")
        )
        yield Page(
            f"/videos/year/{year}/",
            "video_archive/video_year_list.html",
            {"videos": year_videos, "year": year, "year_label": format_fiscal_year(year)},
        )

    for video in videos:
        yield Page(f"/videos/{video.pk}/", "video_archive/video_detail.html", {"video": video, "return_year": None})
        if video.event_date is not None:
            year = _fiscal_year(video.event_date)
            yield Page(
                f"/videos/{video.pk}/",
                "video_archive/video_detail.html",
                {"video": video, "return_year": year},
                query=(("year", str(year)),),
            )
