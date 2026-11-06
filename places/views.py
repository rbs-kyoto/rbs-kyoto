from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import staff_required

from .forms import PlaceForm
from .models import Place


@login_required
@staff_required
def place_list(request):
    places = Place.objects.select_related("parent").annotate(
        equipment_count=Count("equipment", filter=Q(equipment__is_active=True), distinct=True),
    )
    # 親→子の順に並べて、階層が見えるようにする
    ordered = sorted(places, key=lambda place: str(place))
    return render(request, "places/place_list.html", {"places": ordered})


@login_required
@staff_required
def place_create(request):
    form = PlaceForm(request.POST or None, initial={"is_venue": True, "is_storage": False})
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("places:list")
    return render(request, "places/place_form.html", {"form": form, "place": None})


@login_required
@staff_required
def place_edit(request, pk):
    place = get_object_or_404(Place, pk=pk)
    form = PlaceForm(request.POST or None, instance=place)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("places:list")
    return render(request, "places/place_form.html", {"form": form, "place": place})
