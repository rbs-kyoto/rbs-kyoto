from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.urls import reverse
from .models import Pickup, News

APPS = [
    {
        "title": "マニュアル",
        "description": "部内向けの手順書・資料",
        "url_name": "manuals:manual_list",
    },
]

def index(request):
    pickups = Pickup.objects.filter(is_active=True)
    news = News.objects.filter(
        is_active=True
    )
    if not request.user.is_authenticated:
        news = news.filter(
            is_internal=False
        )
    news = news.order_by("-date")[:5]
    apps = [
        {**app, "url": reverse(app["url_name"])}
        for app in APPS
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

def news_all(request):
    news_list = News.objects.filter(
        is_active=True
    )
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
    news = get_object_or_404(
        News,
        pk=pk,
        is_active=True,
    )
    if news.is_internal and not request.user.is_authenticated:
        return redirect("accounts:login")
    return render(
        request,
        "main/news_detail.html",
        {
            "news": news,
        },
    )