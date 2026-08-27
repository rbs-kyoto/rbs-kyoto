from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from .models import Manual


@login_required
def manual_list(request):
    manuals = Manual.objects.filter(is_active=True)

    return render(
        request,
        "manuals/manual_list.html",
        {"manuals": manuals},
    )


@login_required
def manual_detail(request, pk):
    manual = get_object_or_404(Manual, pk=pk, is_active=True)

    with manual.file.open("rb") as f:
        content = f.read().decode("utf-8")

    return render(
        request,
        "manuals/manual_detail.html",
        {
            "manual": manual,
            "content": content,
        },
    )
