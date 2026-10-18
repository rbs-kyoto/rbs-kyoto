from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Video
from .utils import format_fiscal_year


def _visible_videos(user):
    videos = Video.objects.select_related("group")
    if not user.is_staff:
        videos = videos.filter(is_active=True)
    return videos


@login_required
def video_list(request):
    videos = _visible_videos(request.user)
    fiscal_year_counts = {}
    undated_videos = []
    for video in videos:
        if video.event_date is None:
            undated_videos.append(video)
            continue
        fiscal_year = video.event_date.year - (video.event_date.month < 4)
        fiscal_year_counts[fiscal_year] = fiscal_year_counts.get(fiscal_year, 0) + 1

    return render(
        request,
        "video_archive/video_list.html",
        {
            "fiscal_years": [
                {
                    "year": year,
                    "label": format_fiscal_year(year),
                    "count": str(fiscal_year_counts[year]).translate(
                        str.maketrans("0123456789", "０１２３４５６７８９")
                    ),
                }
                for year in sorted(fiscal_year_counts, reverse=True)
            ],
            "undated_videos": undated_videos,
        },
    )


@login_required
def video_year_list(request, year):
    if not 1 <= year <= 9998:
        raise Http404

    videos = _visible_videos(request.user).filter(
        event_date__gte=date(year, 4, 1),
        event_date__lt=date(year + 1, 4, 1),
    )
    return render(
        request,
        "video_archive/video_year_list.html",
        {
            "videos": videos.order_by(
                "group__order",
                "group__name",
                "order",
                "-registered_at",
            ),
            "year": year,
            "year_label": format_fiscal_year(year),
        },
    )


@login_required
def video_detail(request, pk):
    video = get_object_or_404(_visible_videos(request.user), pk=pk)
    try:
        return_year = int(request.GET.get("year", ""))
    except ValueError:
        return_year = None
    if return_year is not None and not 1 <= return_year <= 9998:
        return_year = None

    return render(
        request,
        "video_archive/video_detail.html",
        {"video": video, "return_year": return_year},
    )
