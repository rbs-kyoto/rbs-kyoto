from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from .models import Manual

staff_required = user_passes_test(lambda user: user.is_staff)

SORT_OPTIONS = {
    "date": "-uploaded_at",
    "title": "title",
}
DEFAULT_SORT = "order"


@login_required
def manual_list(request):
    manuals = Manual.objects.all()
    if not request.user.is_staff:
        manuals = manuals.filter(is_active=True)

    sort = request.GET.get("sort")
    if sort in SORT_OPTIONS:
        manuals = manuals.order_by(SORT_OPTIONS[sort])
    else:
        sort = DEFAULT_SORT

    return render(
        request,
        "manuals/manual_list.html",
        {"manuals": manuals, "sort": sort},
    )


@login_required
def manual_detail(request, pk):
    manual = get_object_or_404(Manual, pk=pk)
    if not manual.is_active and not request.user.is_staff:
        raise Http404

    return render(
        request,
        "manuals/manual_detail.html",
        {"manual": manual},
    )


@login_required
@staff_required
def manual_create(request):
    if request.method == "POST":
        manual = Manual(
            title=request.POST.get("title", "").strip(),
            content=request.POST.get("content", ""),
            order=request.POST.get("order") or 0,
            is_active=bool(request.POST.get("is_active")),
        )
        manual.save()

        return redirect("manuals:manual_detail", pk=manual.pk)

    return render(request, "manuals/manual_form.html", {"manual": None})


@login_required
@staff_required
def manual_edit(request, pk):
    manual = get_object_or_404(Manual, pk=pk)

    if request.method == "POST":
        manual.title = request.POST.get("title", "").strip()
        manual.content = request.POST.get("content", "")
        manual.order = request.POST.get("order") or 0
        manual.is_active = bool(request.POST.get("is_active"))
        manual.save()

        return redirect("manuals:manual_detail", pk=manual.pk)

    return render(request, "manuals/manual_form.html", {"manual": manual})
