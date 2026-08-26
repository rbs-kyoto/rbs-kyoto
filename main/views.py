from django.shortcuts import get_object_or_404, render
from .models import Pickup, News

def index(request):
    pickups = Pickup.objects.filter(is_active=True)
    news = News.objects.filter(is_active=True)

    return render(
        request,
        "main/index.html",
        {
            "pickups": pickups,
            "news": news,
        },
    )

def news_all(request):
    news_list = News.objects.filter(
        is_active=True
    ).order_by("-date")

    return render(request, "main/news_all.html", {
        "news_list": news_list,
    })


def news_detail(request, pk):
    news = get_object_or_404(
        News,
        pk=pk,
        is_active=True,
    )

    return render(request, "main/news_detail.html", {
        "news": news,
    })