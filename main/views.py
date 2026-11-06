from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.http import Http404
from django.urls import reverse
from accounts.decorators import staff_required
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
        "title": "Roll",
        "description": "校内名簿・部員・役職の管理",
        "url_name": "roll:list",
        "staff_only": True,
    },
]

def index(request):
    pickups = Pickup.objects.filter(is_active=True)
    news = News.objects.all()
    if not request.user.is_staff:
        news = news.filter(is_active=True)
    if not request.user.is_authenticated:
        news = news.filter(
            is_internal=False
        )
    news = news.order_by("-date")[:5]
    apps = [
        {**app, "url": reverse(app["url_name"])}
        for app in APPS
        if not app.get("staff_only") or request.user.is_staff
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
    news_list = News.objects.all()
    if not request.user.is_staff:
        news_list = news_list.filter(is_active=True)
    if not request.user.is_authenticated:
        news_list = news_list.filter(
            is_internal=False
        )
    news_list = news_list.order_by("-date")
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
    if not news.is_active and not request.user.is_staff:
        raise Http404
    if news.is_internal and not request.user.is_authenticated:
        return redirect("accounts:login")
    return render(
        request,
        "main/news_detail.html",
        {
            "news": news,
        },
    )


@login_required
@staff_required
def news_create(request):
    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES)
        if form.is_valid():
            news = form.save()
            return redirect("main:news_detail", pk=news.pk)
    else:
        form = NewsForm()

    return render(request, "main/news_form.html", {"form": form, "news": None})


@login_required
@staff_required
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