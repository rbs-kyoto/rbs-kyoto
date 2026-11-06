import csv
from datetime import date
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

from accounts.decorators import staff_required
from roll.models import Position, RosterEntry

from .csvio import EquipmentImportError, import_equipment_csv, write_export
from .events import Kind, record_event
from .forms import (
    EquipmentForm,
    EquipmentImportForm,
    LoanForm,
    QRDesignForm,
    ReturnRecordForm,
    StorageLocationForm,
)
from .models import (
    Category,
    Equipment,
    EquipmentHistory,
    Loan,
    LoanLine,
    QRDesign,
    ReturnRecord,
    StorageLocation,
)
from .services import LoanError, change_status, create_loan, record_return


@login_required
def dashboard(request):
    active_equipment = (
        Equipment.objects.filter(is_active=True)
        .select_related("model__category")
        .prefetch_related("loan_lines__returns")
    )
    lines = LoanLine.objects.select_related("equipment__model", "loan").prefetch_related(
        "returns"
    )
    open_usages = [line for line in lines if line.remaining_quantity]
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
            if usage.usage_type == Loan.UsageType.LENDING
        ),
        "carry_out_quantity": sum(
            usage.remaining_quantity
            for usage in open_usages
            if usage.usage_type == Loan.UsageType.CARRY_OUT
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
                Equipment.Condition.LOST,
            ]
        )[:10],
        "recent_equipment": active_equipment.order_by("-created_at")[:8],
        "recent_usages": LoanLine.objects.select_related("equipment__model", "loan")[:8],
        "recent_returns": ReturnRecord.objects.select_related(
            "line__equipment__model", "line__loan", "processed_by"
        )[:8],
    }
    return render(request, "equipment/dashboard.html", context)


@login_required
def equipment_list(request):
    archived = request.GET.get("archived") == "1"
    equipment = Equipment.objects.filter(is_active=not archived).select_related(
        "model__category",
        "model__manufacturer",
        "location",
        "manager",
        "created_by",
        "last_modified_by",
    ).prefetch_related("loan_lines__loan", "loan_lines__returns")
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
            | Q(model__name__icontains=query)
            | Q(model__manufacturer__name__icontains=query)
            | Q(model__model_number__icontains=query)
            | Q(serial_number__icontains=query)
            | Q(receipt_number__icontains=query)
            | Q(qr_inventory_number__iexact=query)
            | Q(location__name__icontains=query)
            | Q(manager__name__icontains=query)
            | Q(loan_lines__loan__destination__icontains=query)
            | Q(loan_lines__loan__destination_entry__name__icontains=query)
        ).distinct()
    if category:
        if category.isdigit():
            equipment = equipment.filter(model__category_id=category)
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
        lines = list(item.loan_lines.all())
        item.latest_usage = next(
            (line for line in lines if line.remaining_quantity),
            lines[0] if lines else None,
        )
    if usage_status:
        items = [item for item in items if item.usage_status == usage_status]
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="equipment.csv"'
        write_export(response, items)
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
            "managers": Position.objects.filter(is_active=True),
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
                    record_event(
                        equipment,
                        Kind.REGISTER,
                        request.user,
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
    original_condition = equipment.condition
    original_values = {
        field: _display_value(equipment, field)
        for field in EquipmentForm.Meta.fields
    }
    if request.method == "POST":
        form = EquipmentForm(request.POST, request.FILES, instance=equipment)
        if form.is_valid():
            # The status goes through change_status below, never through the form.
            changed_fields = [
                field
                for field in form.changed_data
                if field in EquipmentForm.Meta.fields and field != "condition"
            ]
            new_condition = form.cleaned_data["condition"]
            with transaction.atomic():
                updated_equipment = form.save(commit=False)
                updated_equipment.condition = original_condition
                updated_equipment.last_modified_by = request.user
                updated_equipment.save()
                change_status(updated_equipment, new_condition, request.user)
                if (
                    "manufacturer" not in changed_fields
                    and _display_value(updated_equipment, "manufacturer")
                    != original_values["manufacturer"]
                ):
                    changed_fields.append("manufacturer")
                for field_name in changed_fields:
                    record_event(
                        updated_equipment,
                        Kind.UPDATE,
                        request.user,
                        field_name=form.fields[field_name].label,
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
            "model__category",
            "model__manufacturer",
            "location",
            "created_by",
            "last_modified_by",
        ),
        pk=pk,
    )
    if not equipment.is_active and request.GET.get("show_archived") != "1":
        raise Http404
    usages = equipment.loan_lines.select_related("loan").prefetch_related("returns")
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
            "usages": equipment.loan_lines.select_related("loan").prefetch_related(
                "returns"
            ),
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
            line
            for line in equipment.loan_lines.prefetch_related("returns")
            if line.remaining_quantity
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
        record_event(
            equipment,
            Kind.UNREGISTER,
            request.user,
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
        record_event(
            equipment,
            Kind.REACTIVATE,
            request.user,
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
    records = LoanLine.objects.select_related(
        "equipment__model", "loan__created_by"
    ).prefetch_related("returns")
    filter_type = request.GET.get("type", "")
    filter_status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    if filter_type in Loan.UsageType.values:
        records = records.filter(loan__usage_type=filter_type)
    if query:
        records = records.filter(
            Q(loan__destination__icontains=query)
            | Q(loan__recipient__icontains=query)
            | Q(equipment__inventory_number__icontains=query)
            | Q(equipment__model__name__icontains=query)
        )
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
            "query": query,
            "usage_types": Loan.UsageType.choices,
        },
    )


CART_KEY = "equipment_cart"


def _get_cart(request):
    """The lending cart: {equipment id: quantity}, kept in the session."""
    cart = {}
    for entry in request.session.get(CART_KEY, []):
        try:
            cart[int(entry[0])] = max(int(entry[1]), 1)
        except (TypeError, ValueError, IndexError):
            continue
    return cart


def _save_cart(request, cart):
    request.session[CART_KEY] = [[pk, quantity] for pk, quantity in cart.items()]


def _posted_quantities(post, ids):
    """Quantities typed next to each cart row (quantity_<id>), default 1."""
    quantities = {}
    for pk in ids:
        raw = post.get(f"quantity_{pk}")
        if raw is None and len(ids) == 1:
            raw = post.get("quantity")  # simple single-item form
        try:
            quantities[pk] = int(raw) if raw not in (None, "") else 1
        except ValueError:
            quantities[pk] = 0
    return quantities


def _lendable_equipment():
    return Equipment.objects.filter(
        is_active=True, condition__in=Equipment.LOANABLE_CONDITIONS
    ).select_related("model__category")


def _posted_ids(post):
    ids = []
    for raw in post.getlist("equipment"):
        if raw.isdigit() and int(raw) not in ids:
            ids.append(int(raw))
    return ids


@login_required
def cart_add(request, pk=None):
    if request.method != "POST":
        raise Http404
    ids = _posted_ids(request.POST)
    cart = {**_get_cart(request), **_posted_quantities(request.POST, ids)}
    raw = pk if pk is not None else request.POST.get("add_equipment", "")
    if str(raw).isdigit() and _lendable_equipment().filter(pk=raw).exists():
        cart.setdefault(int(raw), 1)
    elif raw:
        messages.error(request, "貸出できない備品です。")
    _save_cart(request, {k: max(v, 1) for k, v in cart.items()})
    return redirect("equipment:lending_register")


@login_required
def cart_remove(request, pk):
    if request.method != "POST":
        raise Http404
    ids = _posted_ids(request.POST)
    cart = {**_get_cart(request), **_posted_quantities(request.POST, ids)}
    cart.pop(pk, None)
    _save_cart(request, {k: max(v, 1) for k, v in cart.items()})
    return redirect("equipment:lending_register")


@login_required
def usage_create(request):
    cart = _get_cart(request)
    quantities = None
    if request.method == "POST":
        form = LoanForm(request.POST)
        ids = _posted_ids(request.POST)
        quantities = _posted_quantities(request.POST, ids)
        if form.is_valid():
            if not ids:
                form.add_error(None, "貸出する備品を選択してください。")
            elif any(quantity < 1 for quantity in quantities.values()):
                form.add_error(None, "数量は1以上の整数で入力してください。")
            else:
                try:
                    loan = create_loan(
                        request.user,
                        [(pk, quantities[pk]) for pk in ids],
                        **form.loan_fields(),
                    )
                except LoanError as error:
                    form.add_error(None, error.message)
                else:
                    request.session.pop(CART_KEY, None)
                    messages.success(request, "貸出・持出を登録しました。")
                    return redirect("equipment:usage_detail", pk=loan.pk)
        cart = quantities
    else:
        equipment_id = request.GET.get("equipment", "")
        if equipment_id.isdigit() and _lendable_equipment().filter(pk=equipment_id).exists():
            cart.setdefault(int(equipment_id), 1)
            _save_cart(request, cart)
            return redirect("equipment:lending_register")
        form = LoanForm()
    by_pk = {item.pk: item for item in _lendable_equipment().filter(pk__in=cart)}
    rows = [
        {"equipment": by_pk[pk], "quantity": cart[pk]} for pk in cart if pk in by_pk
    ]
    return render(
        request,
        "equipment/usage_form.html",
        {
            "form": form,
            "rows": rows,
            "picker": _lendable_equipment().exclude(pk__in=[r["equipment"].pk for r in rows]),
        },
    )


@login_required
def usage_detail(request, pk):
    loan = get_object_or_404(
        Loan.objects.select_related("created_by", "responsible_person").prefetch_related(
            "lines__equipment__model", "lines__returns__processed_by"
        ),
        pk=pk,
    )
    return render(
        request,
        "equipment/usage_detail.html",
        {
            "loan": loan,
            "return_conditions": [
                (value, label)
                for value, label in ReturnRecord.Condition.choices
                if value != ReturnRecord.Condition.DAMAGED
            ],
        },
    )


@login_required
def loan_return_all(request, pk):
    """Return every ticked line of a loan at once (the whole remaining quantity)."""
    if request.method != "POST":
        raise Http404
    loan = get_object_or_404(Loan.objects.prefetch_related("lines__returns"), pk=pk)
    valid_conditions = {
        value
        for value, _ in ReturnRecord.Condition.choices
        if value != ReturnRecord.Condition.DAMAGED
    }
    chosen = [
        line
        for line in loan.lines.all()
        if line.remaining_quantity and request.POST.get(f"return_{line.pk}")
    ]
    if not chosen:
        messages.error(request, "返却する備品をチェックしてください。")
        return redirect("equipment:usage_detail", pk=loan.pk)
    try:
        with transaction.atomic():
            for line in chosen:
                condition = request.POST.get(f"condition_{line.pk}", "normal")
                if condition not in valid_conditions:
                    condition = ReturnRecord.Condition.NORMAL
                record_return(
                    line.pk,
                    request.user,
                    ReturnRecord(
                        quantity=line.remaining_quantity,
                        returned_at=timezone.now(),
                        confirmed_by=request.POST.get("confirmed_by", "").strip(),
                        condition=condition,
                        condition_details=request.POST.get(f"details_{line.pk}", "").strip(),
                    ),
                )
    except LoanError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, f"{len(chosen)}件の返却を記録しました。")
    return redirect("equipment:usage_detail", pk=loan.pk)


@login_required
def return_usage(request, pk):
    line = get_object_or_404(
        LoanLine.objects.select_related("equipment__model", "loan").prefetch_related(
            "returns"
        ),
        pk=pk,
    )
    if request.method == "POST":
        form = ReturnRecordForm(request.POST)
        if form.is_valid():
            try:
                record_return(line.pk, request.user, form.save(commit=False))
            except LoanError as error:
                form.add_error(error.field, error.message)
            else:
                messages.success(request, "返却を記録しました。")
                return redirect("equipment:usage_detail", pk=line.loan_id)
    else:
        form = ReturnRecordForm()
    return render(
        request,
        "equipment/return_form.html",
        {"form": form, "usage": line},
    )


@login_required
def category_list(request):
    categories = Category.objects.annotate(
        equipment_count=Count(
            "equipment_models__items",
            filter=Q(equipment_models__items__is_active=True),
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
@staff_required
def equipment_import(request):
    result = None
    error = None
    if request.method == "POST":
        form = EquipmentImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                count = import_equipment_csv(form.cleaned_data["csv_file"], request.user)
            except (EquipmentImportError, csv.Error) as import_error:
                error = str(import_error)
            else:
                result = f"{count}件の備品を登録しました。"
                form = EquipmentImportForm()
    else:
        form = EquipmentImportForm()
    return render(
        request,
        "equipment/import_csv.html",
        {"form": form, "error": error, "result": result},
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


@login_required
@staff_required
def activity(request):
    """Audit view: everything that happened, filterable by kind, actor and period."""
    events = EquipmentHistory.objects.select_related(
        "equipment__model", "changed_by"
    )
    kind = request.GET.get("kind", "")
    actor = request.GET.get("user", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    query = request.GET.get("q", "").strip()
    if kind in EquipmentHistory.Kind.values:
        events = events.filter(kind=kind)
    if actor.isdigit():
        events = events.filter(changed_by_id=actor)
    for raw, lookup in ((date_from, "changed_at__date__gte"), (date_to, "changed_at__date__lte")):
        try:
            events = events.filter(**{lookup: date.fromisoformat(raw)}) if raw else events
        except ValueError:
            pass
    if query:
        events = events.filter(
            Q(equipment__inventory_number__icontains=query)
            | Q(equipment__model__name__icontains=query)
            | Q(field_name__icontains=query)
            | Q(reason__icontains=query)
        )
    page_obj = Paginator(events, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "equipment/activity.html",
        {
            "page_obj": page_obj,
            "kinds": EquipmentHistory.Kind.choices,
            "actors": get_user_model().objects.filter(equipment_changes__isnull=False).distinct().order_by("username"),
            "selected": {"kind": kind, "user": actor, "from": date_from, "to": date_to, "q": query},
            "query_string": params.urlencode(),
        },
    )
