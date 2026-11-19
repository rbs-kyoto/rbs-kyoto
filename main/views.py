from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.http import Http404
from django.urls import reverse
from accounts.audience import can_view, is_club_editor, is_club_member, visible_audiences
from accounts.decorators import club_editor_required
from .forms import NewsForm
from .models import Pickup, News, SitePage

APPS = [
    {
        "title": "Manual",
        "description": "部内向けの手順書・資料",
        "url_name": "manuals:manual_list",
    },
    {
        "title": "Video Archive",
        "description": "過去の動画アーカイブ",
        "url_name": "video_archive:video_list",
    },
    {
        "title": "Schedule",
        "description": "部活の予定・担当・出欠",
        "url_name": "schedule:calendar",
    },
    {
        "title": "Equipment",
        "description": "機材・備品の管理",
        "url_name": "equipment:dashboard",
    },
    {
        "title": "Revise",
        "description": "原稿の投稿と添削",
        "url_name": "revise:index",
    },
    {
        "title": "Places",
        "description": "場所マスターの管理(予定・機材の保管場所)",
        "url_name": "places:list",
        "editor_only": True,
    },
    {
        "title": "Roll",
        "description": "校内名簿・部員・役職の管理",
        "url_name": "roll:list",
        "editor_only": True,
    },
]


def _visible_news(user):
    """user の立場(校外・部外・部内)で見てよいお知らせ。非公開のものは編集担当だけに見せる。"""
    news = News.objects.filter(visibility__in=visible_audiences(user))
    if not is_club_editor(user):
        news = news.filter(is_active=True)
    return news


def index(request):
    pickups = Pickup.objects.filter(is_active=True)
    news = _visible_news(request.user).order_by("-date")[:5]
    # Apps はどれも部内専用。部員にだけ並べ、管理系は編集担当にだけ見せる。
    apps = [
        {**app, "url": reverse(app["url_name"])}
        for app in APPS
        if is_club_member(request.user)
        and (not app.get("editor_only") or is_club_editor(request.user))
    ]
    return render(
        request,
        "main/index.html",
        {
            "pickups": pickups,
            "news": news,
            "apps": apps,
        },
    )


def about(request):
    return render(request, "main/about.html")


def site_page(request, slug):
    page = get_object_or_404(SitePage, slug=slug)
    return render(request, "main/site_page.html", {"page": page})


def news_all(request):
    news_list = _visible_news(request.user).order_by("-date")
    paginator = Paginator(news_list, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "main/news_all.html",
        {
            "news_list": page_obj,
            "page_obj": page_obj,
        },
    )


def news_detail(request, pk):
    news = get_object_or_404(News, pk=pk)
    if not news.is_active and not is_club_editor(request.user):
        raise Http404
    if not can_view(request.user, news.visibility):
        # 未ログインならログインを促す。ログイン済みで見られない(部外の人が部内向けを
        # 開いた)場合は、記事があること自体を伏せる。
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        raise Http404
    return render(
        request,
        "main/news_detail.html",
        {
            "news": news,
        },
    )


@club_editor_required
def news_create(request):
    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES)
        if form.is_valid():
            news = form.save()
            return redirect("main:news_detail", pk=news.pk)
    else:
        form = NewsForm()

    return render(request, "main/news_form.html", {"form": form, "news": None})


@club_editor_required
def news_edit(request, pk):
    news = get_object_or_404(News, pk=pk)

    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES, instance=news)
        if form.is_valid():
            form.save()
            return redirect("main:news_detail", pk=news.pk)
    else:
        form = NewsForm(instance=news)

    return render(request, "main/news_form.html", {"form": form, "news": news})