from django.contrib import admin

from .events import Kind, record_event
from .forms import EquipmentForm, StorageLocationForm
from .services import change_status
from .models import (
    Category,
    Equipment,
    EquipmentHistory,
    EquipmentModel,
    Manufacturer,
    QRDesign,
    Loan,
    LoanLine,
    ReturnRecord,
    StorageLocation,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "english_name")
    search_fields = ("code", "name", "english_name", "examples")
    ordering = ("code",)
    readonly_fields = ("code",)

    def get_readonly_fields(self, request, obj=None):
        if obj is None or not obj.equipment_models.exists():
            return ()
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(EquipmentModel)
class EquipmentModelAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "manufacturer", "model_number", "unit")
    list_filter = ("category",)
    search_fields = ("name", "manufacturer__name", "model_number")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    form = EquipmentForm
    list_display = (
        "inventory_number",
        "name",
        "category",
        "quantity",
        "unit",
        "condition",
        "is_active",
    )
    list_filter = ("model__category", "condition", "is_active")
    search_fields = (
        "inventory_number",
        "model__name",
        "model__manufacturer__name",
        "model__model_number",
        "serial_number",
        "receipt_number",
        "qr_token",
        "manager__name",
    )
    readonly_fields = (
        "inventory_number",
        "qr_token",
        "created_by",
        "last_modified_by",
        "created_at",
        "updated_at",
        "unregistered_at",
        "unregistered_by",
    )
    exclude = ("unregistered_at", "unregistered_by", "unregistration_reason")

    def save_model(self, request, obj, form, change):
        previous_values = {}
        changed_fields = [
            field
            for field in form.changed_data
            if field in EquipmentForm.Meta.fields and field != "condition"
        ]
        new_condition = obj.condition
        if change:
            previous = Equipment.objects.get(pk=obj.pk)
            for field_name in changed_fields:
                previous_values[field_name] = getattr(previous, field_name)
            # The status goes through change_status so the rules always apply.
            obj.condition = previous.condition
            obj.last_modified_by = request.user
        else:
            obj.created_by = request.user
            obj.last_modified_by = request.user
        super().save_model(request, obj, form, change)
        if not change:
            record_event(
                obj,
                Kind.REGISTER,
                request.user,
                new_value=f"{obj.inventory_number} {obj.name}",
            )
            return
        for field_name in changed_fields:
            old_value = previous_values[field_name]
            new_value = getattr(obj, field_name)
            record_event(
                obj,
                Kind.UPDATE,
                request.user,
                field_name=form.fields[field_name].label,
                old_value=old_value,
                new_value=new_value,
            )
        change_status(obj, new_condition, request.user)

@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    form = StorageLocationForm
    list_display = ("name", "code", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "description")

    def has_delete_permission(self, request, obj=None):
        return False


class LoanLineInline(admin.TabularInline):
    model = LoanLine
    extra = 0
    can_delete = False
    readonly_fields = ("equipment", "quantity")


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "destination",
        "usage_type",
        "started_at",
        "due_at",
        "created_by",
    )
    list_filter = ("usage_type",)
    search_fields = (
        "lines__equipment__inventory_number",
        "destination",
        "recipient",
    )
    readonly_fields = ("created_by", "created_at")
    inlines = [LoanLineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EquipmentHistory)
class EquipmentHistoryAdmin(admin.ModelAdmin):
    list_display = ("equipment", "kind", "field_name", "changed_by", "changed_at")
    list_filter = ("kind", "changed_at")
    search_fields = (
        "equipment__inventory_number",
        "equipment__model__name",
        "field_name",
    )
    readonly_fields = (
        "equipment",
        "kind",
        "changed_at",
        "changed_by",
        "field_name",
        "old_value",
        "new_value",
        "reason",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ReturnRecord)
class ReturnRecordAdmin(admin.ModelAdmin):
    list_display = ("line", "quantity", "returned_at", "condition", "processed_by")
    list_filter = ("condition", "returned_at")
    readonly_fields = (
        "line",
        "quantity",
        "returned_at",
        "confirmed_by",
        "condition",
        "condition_details",
        "notes",
        "processed_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(QRDesign)
class QRDesignAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not QRDesign.objects.exists()
