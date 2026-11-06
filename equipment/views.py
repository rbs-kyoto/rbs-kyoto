import csv
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Prefetch, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

from roll.models import RosterEntry

from .forms import (
    EquipmentForm,
    QRDesignForm,
    ReturnRecordForm,
    StorageLocationForm,
    UsageRecordForm,
)
from .models import (
    Category,
    Equipment,
    EquipmentHistory,
    QRDesign,
    ReturnRecord,
    StorageLocation,
    UsageRecord,
)


@login_required
def dashboard(request):
    active_equipment = Equipment.objects.filter(is_active=True).select_related(
        "category"
    ).prefetch_related(
        Prefetch(
            "usage_records",
            queryset=UsageRecord.objects.prefetch_related("returns"),
            to_attr="usage_cache",
        )
    )
    usages = UsageRecord.objects.filter(
        quantity__gt=0,
    ).select_related("equipment").prefetch_related("returns")
    open_usages = [
        usage for usage in usages if usage.remaining_quantity
    ]
    overdue_usages = [usage for usage in open_usages if usage.is_overdue]
    context = {
        "equipment_type_count": active_equipment.count(),
        "equipment_quantity": active_equipment.aggregate(total=Sum("quantity"))[
            "total"
        ]
        or 0,
        "lending_quantity": sum(
            usage.remaining_quantity
            for usage in open_usages
            if usage.usage_type == UsageRecord.UsageType.LENDING
        ),
        "carry_out_quantity": sum(
            usage.remaining_quantity
            for usage in open_usages
            if usage.usage_type == UsageRecord.UsageType.CARRY_OUT
        ),
        "stored_quantity": sum(
            equipment.stored_quantity for equipment in active_equipment
        ),
        "overdue_usages": overdue_usages[:10],
        "overdue_count": len(overdue_usages),
        "attention_equipment": active_equipment.filter(
            condition__in=[
                Equipment.Condition.INSPECTION,
                Equipment.Condition.REPAIR,
                Equipment.Condition.BROKEN,
                Equipment.Condition.DISABLED,
            ]
        )[:10],
        "recent_equipment": active_equipment.order_by("-created_at")[:8],
        "recent_usages": UsageRecord.objects.select_related("equipment")[:8],
        "recent_returns": ReturnRecord.objects.select_related(
            "usage__equipment", "processed_by"
        )[:8],
    }
    return render(request, "equipment/dashboard.html", context)


@login_required
def equipment_list(request):
    archived = request.GET.get("archived") == "1"
    equipment = Equipment.objects.filter(is_active=not archived).select_related(
        "category",
        "manufacturer",
        "location",
        "manager",
        "created_by",
        "last_modified_by",
    ).prefetch_related(
        Prefetch(
            "usage_records",
            queryset=UsageRecord.objects.prefetch_related("returns"),
            to_attr="usage_cache",
        )
    )
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    condition = request.GET.get("condition", "").strip()
    location = request.GET.get("location", "").strip()
    manager = request.GET.get("manager", "").strip()
    usage_status = request.GET.get("usage_status", "").strip()

    if query:
        equipment = equipment.filter(
            Q(inventory_number__icontains=query)
            | Q(qr_token__iexact=query)
            | Q(name__icontains=query)
            | Q(manufacturer__name__icontains=query)
            | Q(model_number__icontains=query)
            | Q(serial_number__icontains=query)
            | Q(receipt_number__icontains=query)
            | Q(qr_inventory_number__iexact=query)
            | Q(location__name__icontains=query)
            | Q(manager__name__icontains=query)
            | Q(usage_records__destination__icontains=query)
            | Q(usage_records__destination_entry__name__icontains=query)
        ).distinct()
    if category:
        if category.isdigit():
            equipment = equipment.filter(category_id=category)
        else:
            equipment = equipment.none()
    if condition:
        equipment = equipment.filter(condition=condition)
    if location:
        if location.isdigit():
            equipment = equipment.filter(location_id=location)
        else:
            equipment = equipment.none()
    if manager:
        if manager.isdigit():
            equipment = equipment.filter(manager_id=manager)
        else:
            equipment = equipment.none()

    items = list(equipment)
    for item in items:
        active_usages = [
            usage for usage in item.usage_cache if usage.remaining_quantity
        ]
        if active_usages:
            item.latest_usage = active_usages[0]
        else:
            item.latest_usage = next(
                (usage for usage in item.usage_cache if not usage.remaining_quantity),
                None,
            )
    if usage_status:
        items = [item for item in items if item.usage_status == usage_status]
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="equipment.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            [
                "備品番号",
                "備品名",
                "分類",
                "メーカー",
                "型番",
                "保有数量",
                "単位",
                "利用状況",
                "保管場所",
                "管理担当者",
                "登録日時",
                "最終更新日時",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.inventory_number,
                    item.name,
                    str(item.category),
                    item.manufacturer or "",
                    item.model_number,
                    item.quantity,
                    item.unit,
                    item.usage_status,
                    str(item.location or ""),
                    item.manager,
                    timezone.localtime(item.created_at).strftime("%Y-%m-%d %H:%M"),
                    timezone.localtime(item.updated_at).strftime("%Y-%m-%d %H:%M"),
                ]
            )
        return response

    page_size = request.GET.get("page_size", "25")
    if page_size not in {"10", "25", "100"}:
        page_size = "25"
    paginator = Paginator(items, int(page_size))
    page_obj = paginator.get_page(request.GET.get("page"))
    items = list(page_obj.object_list)
    page_range = paginator.get_elided_page_range(page_obj.number)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_params.pop("export", None)
    query_string = query_params.urlencode()
    csv_url = reverse("equipment:list")
    if query_string:
        csv_url = f"{csv_url}?{query_string}&export=csv"
    else:
        csv_url = f"{csv_url}?export=csv"
    return render(
        request,
        "equipment/equipment_list.html",
        {
            "equipment_list": items,
            "page_obj": page_obj,
            "query": query,
            "selected_category": category,
            "selected_condition": condition,
            "selected_location": location,
            "manager": manager,
            "selected_usage_status": usage_status,
            "archived": archived,
            "page_size": page_size,
            "page_range": page_range,
            "query_string": query_string,
            "csv_url": csv_url,
            "categories": Category.objects.all(),
            "conditions": Equipment.Condition.choices,
            "locations": StorageLocation.objects.filter(is_active=True),
            "managers": RosterEntry.objects.exclude(
                entry_type=RosterEntry.EntryType.ORGANIZATION
            ).order_by("name"),
        },
    )


@login_required
def equipment_create(request):
    if request.method == "POST":
        form = EquipmentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    equipment = form.save(commit=False)
                    equipment.created_by = request.user
                    equipment.last_modified_by = request.user
                    equipment.save()
                    EquipmentHistory.objects.create(
                        equipment=equipment,
                        changed_by=request.user,
                        field_name="登録",
                        new_value=f"{equipment.inventory_number} {equipment.name}",
                    )
            except IntegrityError:
                inventory_number = getattr(
                    form, "generated_inventory_number", ""
                )
                if not inventory_number or not Equipment.objects.filter(
                    inventory_number=inventory_number
                ).exists():
                    raise
                form.add_error(
                    None,
                    "同時に登録が行われたため備品番号を確保できませんでした。もう一度登録してください。",
                )
            else:
                messages.success(request, "備品を登録しました。")
                return redirect("equipment:detail", pk=equipment.pk)
    else:
        form = EquipmentForm()
    return render(
        request,
        "equipment/equipment_form.html",
        {"form": form, "is_new": True},
    )


def _display_value(equipment, field_name):
    value = getattr(equipment, field_name)
    if field_name == "location":
        return str(value) if value else ""
    if field_name == "category":
        return str(value)
    if field_name == "manufacturer":
        return str(value) if value else ""
    if field_name == "condition":
        return equipment.get_condition_display()
    return str(value) if value is not None else ""


@login_required
def equipment_edit(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk, is_active=True)
    original_values = {
        field: _display_value(equipment, field)
        for field in EquipmentForm.Meta.fields
    }
    if request.method == "POST":
        form = EquipmentForm(request.POST, request.FILES, instance=equipment)
        if form.is_valid():
            changed_fields = [
                field
                for field in form.changed_data
                if field in EquipmentForm.Meta.fields
            ]
            with transaction.atomic():
                updated_equipment = form.save(commit=False)
                updated_equipment.last_modified_by = request.user
                updated_equipment.save()
                if (
                    "manufacturer" not in changed_fields
                    and _display_value(updated_equipment, "manufacturer")
                    != original_values["manufacturer"]
                ):
                    changed_fields.append("manufacturer")
                for field_name in changed_fields:
                    EquipmentHistory.objects.create(
                        equipment=updated_equipment,
                        changed_by=request.user,
                        field_name=updated_equipment._meta.get_field(
                            field_name
                        ).verbose_name,
                        old_value=original_values[field_name],
                        new_value=_display_value(updated_equipment, field_name),
                    )
            messages.success(request, "備品情報を更新しました。")
            return redirect("equipment:detail", pk=equipment.pk)
    else:
        form = EquipmentForm(instance=equipment)
    return render(
        request,
        "equipment/equipment_form.html",
        {"form": form, "equipment": equipment, "is_new": False},
    )


@login_required
def equipment_detail(request, pk):
    equipment = get_object_or_404(
        Equipment.objects.select_related(
            "category", "location", "created_by", "last_modified_by"
        ),
        pk=pk,
    )
    if not equipment.is_active and request.GET.get("show_archived") != "1":
        raise Http404
    usages = equipment.usage_records.prefetch_related("returns").all()
    current_usages = [usage for usage in usages if usage.remaining_quantity]
    return render(
        request,
        "equipment/equipment_detail.html",
        {
            "equipment": equipment,
            "current_usages": current_usages,
            "recent_usages": usages[:10],
        },
    )


@login_required
def equipment_history(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    return render(
        request,
        "equipment/equipment_history.html",
        {
            "equipment": equipment,
            "changes": equipment.history.select_related("changed_by"),
            "usages": equipment.usage_records.prefetch_related("returns"),
        },
    )


@login_required
def unregister_equipment(request, pk):
    if request.method != "POST":
        raise Http404
    with transaction.atomic():
        equipment = get_object_or_404(
            Equipment.objects.select_for_update(), pk=pk, is_active=True
        )
        open_usages = [
            usage
            for usage in equipment.usage_records.prefetch_related("returns")
            if usage.remaining_quantity
        ]
        if open_usages:
            messages.error(
                request,
                "未返却の貸出・持出記録があるため登録解除できません。先に返却処理をしてください。",
            )
            return redirect("equipment:detail", pk=pk)
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "登録解除理由を入力してください。")
            return redirect("equipment:detail", pk=pk)
        equipment.is_active = False
        equipment.unregistered_at = timezone.now()
        equipment.unregistered_by = request.user
        equipment.unregistration_reason = reason
        equipment.last_modified_by = request.user
        equipment.save()
        EquipmentHistory.objects.create(
            equipment=equipment,
            changed_by=request.user,
            field_name="登録状態",
            old_value="管理中",
            new_value="登録解除",
            reason=reason,
        )
    messages.success(request, "備品を登録解除しました。履歴は保持されています。")
    return redirect(f"{reverse('equipment:list')}?archived=1")


@login_required
def reactivate_equipment(request, pk):
    if request.method != "POST":
        raise Http404
    with transaction.atomic():
        equipment = get_object_or_404(
            Equipment.objects.select_for_update(), pk=pk, is_active=False
        )
        equipment.is_active = True
        equipment.unregistered_at = None
        equipment.unregistered_by = None
        equipment.unregistration_reason = ""
        equipment.last_modified_by = request.user
        equipment.save()
        EquipmentHistory.objects.create(
            equipment=equipment,
            changed_by=request.user,
            field_name="登録状態",
            old_value="登録解除",
            new_value="管理中",
        )
    messages.success(request, "備品を再有効化しました。")
    return redirect("equipment:detail", pk=pk)


@login_required
def scan(request):
    query = request.GET.get("q", "").strip()
    if query:
        equipment = Equipment.objects.filter(is_active=True).filter(
            Q(qr_token__iexact=query)
            | Q(inventory_number__iexact=query)
            | Q(qr_inventory_number__iexact=query)
        ).first()
        if equipment:
            return redirect("equipment:detail", pk=equipment.pk)
        messages.error(request, "該当する備品が見つかりませんでした。")
    return render(request, "equipment/scan.html")


@login_required
def qr_lookup(request, token):
    equipment = get_object_or_404(
        Equipment, qr_token=token, is_active=True
    )
    return redirect("equipment:detail", pk=equipment.pk)


def _qr_response(equipment, output_format):
    design = QRDesign.current()
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=design.box_size,
        border=design.border,
    )
    qr.add_data(equipment.qr_inventory_number)
    qr.make(fit=True)
    if output_format == "svg":
        image = qr.make_image(
            image_factory=SvgPathImage,
            fill_color=design.foreground,
            back_color=design.background,
        )
        output = BytesIO()
        image.save(output)
        response = HttpResponse(output.getvalue(), content_type="image/svg+xml")
        extension = "svg"
    else:
        image = qr.make_image(
            fill_color=design.foreground,
            back_color=design.background,
        )
        output = BytesIO()
        image.save(output, format="PNG")
        response = HttpResponse(output.getvalue(), content_type="image/png")
        extension = "png"
    response["Content-Disposition"] = (
        f'attachment; filename="{equipment.inventory_number}.{extension}"'
    )
    return response


@login_required
def qr_display(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    if not equipment.is_active and request.GET.get("show_archived") != "1":
        raise Http404
    return render(request, "equipment/qr_display.html", {"equipment": equipment})


@login_required
def qr_download(request, pk, output_format="png"):
    equipment = get_object_or_404(Equipment, pk=pk)
    if not equipment.is_active and request.GET.get("show_archived") != "1":
        raise Http404
    if output_format not in {"png", "svg"}:
        raise Http404
    return _qr_response(equipment, output_format)


@login_required
def usage_list(request):
    records = UsageRecord.objects.select_related("equipment", "created_by").prefetch_related(
        "returns"
    )
    filter_type = request.GET.get("type", "")
    filter_status = request.GET.get("status", "")
    if filter_type in UsageRecord.UsageType.values:
        records = records.filter(usage_type=filter_type)
    all_records = list(records)
    if filter_status == "open":
        all_records = [record for record in all_records if record.remaining_quantity]
    elif filter_status == "overdue":
        all_records = [record for record in all_records if record.is_overdue]
    elif filter_status == "closed":
        all_records = [record for record in all_records if not record.remaining_quantity]
    return render(
        request,
        "equipment/usage_list.html",
        {
            "records": all_records,
            "selected_type": filter_type,
            "selected_status": filter_status,
            "usage_types": UsageRecord.UsageType.choices,
        },
    )


@login_required
def usage_create(request):
    if request.method == "POST":
        form = UsageRecordForm(request.POST)
        if form.is_valid():
            equipment_id = form.cleaned_data["equipment"].pk
            with transaction.atomic():
                Equipment.objects.filter(pk=equipment_id).update(
                    updated_at=F("updated_at")
                )
                equipment = get_object_or_404(
                    Equipment.objects.select_for_update(),
                    pk=equipment_id,
                    is_active=True,
                )
                if equipment.condition in {
                    Equipment.Condition.REPAIR,
                    Equipment.Condition.BROKEN,
                    Equipment.Condition.DISABLED,
                }:
                    form.add_error(
                        "equipment",
                        "修理中・故障・使用停止中の備品は貸出できません。",
                    )
                elif form.cleaned_data["quantity"] > equipment.available_quantity:
                    form.add_error(
                        "quantity",
                        f"貸出可能数量を超えています（現在 {equipment.available_quantity}"
                        f"{equipment.unit}）。",
                    )
                else:
                    usage = form.save(commit=False)
                    usage.equipment = equipment
                    usage.created_by = request.user
                    usage.save()
                    EquipmentHistory.objects.create(
                        equipment=equipment,
                        changed_by=request.user,
                        field_name="貸出・持出",
                        new_value=(
                            f"{usage.get_usage_type_display()} {usage.destination} "
                            f"{usage.quantity}{equipment.unit}"
                        ),
                    )
                    messages.success(request, "貸出・持出を登録しました。")
                    return redirect("equipment:usage_detail", pk=usage.pk)
    else:
        initial = {}
        equipment_id = request.GET.get("equipment", "")
        if equipment_id.isdigit() and Equipment.objects.filter(
            pk=equipment_id, is_active=True
        ).exists():
            initial["equipment"] = equipment_id
        form = UsageRecordForm(initial=initial)
    return render(request, "equipment/usage_form.html", {"form": form})


@login_required
def usage_detail(request, pk):
    usage = get_object_or_404(
        UsageRecord.objects.select_related("equipment", "created_by").prefetch_related(
            "returns__processed_by"
        ),
        pk=pk,
    )
    return render(request, "equipment/usage_detail.html", {"usage": usage})


@login_required
def return_usage(request, pk):
    usage = get_object_or_404(
        UsageRecord.objects.select_related("equipment").prefetch_related("returns"),
        pk=pk,
    )
    if request.method == "POST":
        form = ReturnRecordForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                UsageRecord.objects.filter(pk=pk).update(quantity=F("quantity"))
                usage = get_object_or_404(
                    UsageRecord.objects.select_for_update().select_related("equipment"),
                    pk=pk,
                )
                remaining = usage.remaining_quantity
                if form.cleaned_data["quantity"] > remaining:
                    form.add_error(
                        "quantity",
                        f"返却可能数量を超えています（残り {remaining}"
                        f"{usage.equipment.unit}）。",
                    )
                else:
                    returned = form.save(commit=False)
                    returned.usage = usage
                    returned.processed_by = request.user
                    returned.save()
                    EquipmentHistory.objects.create(
                        equipment=usage.equipment,
                        changed_by=request.user,
                        field_name="返却",
                        new_value=(
                            f"{returned.quantity}{usage.equipment.unit} "
                            f"{returned.get_condition_display()}"
                        ),
                        reason=returned.condition_details,
                    )
                    messages.success(request, "返却を記録しました。")
                    return redirect("equipment:usage_detail", pk=usage.pk)
    else:
        form = ReturnRecordForm()
    return render(
        request,
        "equipment/return_form.html",
        {"form": form, "usage": usage},
    )


@login_required
def category_list(request):
    categories = Category.objects.annotate(
        equipment_count=Count(
            "equipment", filter=Q(equipment__is_active=True)
        )
    )
    return render(
        request,
        "equipment/category_list.html",
        {"categories": categories},
    )


@login_required
def location_list(request):
    locations = StorageLocation.objects.select_related("parent").annotate(
        equipment_count=Count("equipment", filter=Q(equipment__is_active=True))
    )
    return render(
        request,
        "equipment/location_list.html",
        {"locations": locations},
    )


@login_required
def location_create(request):
    if request.method == "POST":
        form = StorageLocationForm(request.POST)
        if form.is_valid():
            location = form.save()
            messages.success(request, "保管場所を登録しました。")
            return redirect("equipment:locations")
    else:
        form = StorageLocationForm()
    return render(
        request,
        "equipment/location_form.html",
        {"form": form, "is_new": True},
    )


@login_required
def location_edit(request, pk):
    location = get_object_or_404(StorageLocation, pk=pk)
    if request.method == "POST":
        form = StorageLocationForm(request.POST, instance=location)
        if form.is_valid():
            form.save()
            messages.success(request, "保管場所を更新しました。")
            return redirect("equipment:locations")
    else:
        form = StorageLocationForm(instance=location)
    return render(
        request,
        "equipment/location_form.html",
        {"form": form, "location": location, "is_new": False},
    )


@login_required
def settings_view(request):
    design = QRDesign.current()
    if request.method == "POST":
        form = QRDesignForm(request.POST, instance=design)
        if form.is_valid():
            form.save()
            messages.success(request, "QRコードの共通デザインを保存しました。")
            return redirect("equipment:settings")
    else:
        form = QRDesignForm(instance=design)
    return render(request, "equipment/settings.html", {"form": form})
