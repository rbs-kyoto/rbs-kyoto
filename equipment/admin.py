from django.contrib import admin

from .events import Kind, record_event
from .forms import EquipmentForm
from .models import (
    Category,
    Equipment,
    EquipmentHistory,
    Manufacturer,
    QRDesign,
    ReturnRecord,
    UsageRecord,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "english_name")
    search_fields = ("code", "name", "english_name", "examples")
    ordering = ("code",)
    readonly_fields = ("code",)

    def get_readonly_fields(self, request, obj=None):
        if obj is None or not obj.equipment.exists():
            return ()
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


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
    list_filter = ("category", "condition", "is_active")
    search_fields = (
        "inventory_number",
        "name",
        "manufacturer__name",
        "model_number",
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
            if field in EquipmentForm.Meta.fields
        ]
        if change:
            previous = Equipment.objects.get(pk=obj.pk)
            for field_name in changed_fields:
                previous_values[field_name] = getattr(previous, field_name)
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
            field = obj._meta.get_field(field_name)
            old_value = previous_values[field_name]
            new_value = getattr(obj, field_name)
            record_event(
                obj,
                Kind.STATUS if field_name == "condition" else Kind.UPDATE,
                request.user,
                field_name=field.verbose_name,
                old_value=old_value,
                new_value=new_value,
            )

class ReturnRecordInline(admin.TabularInline):
    model = ReturnRecord
    extra = 0
    can_delete = False
    readonly_fields = (
        "quantity",
        "returned_at",
        "confirmed_by",
        "condition",
        "condition_details",
        "processed_by",
        "created_at",
    )


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = (
        "equipment",
        "usage_type",
        "destination",
        "quantity",
        "started_at",
        "due_at",
        "created_by",
    )
    list_filter = ("usage_type",)
    search_fields = ("equipment__inventory_number", "destination", "recipient")
    readonly_fields = ("created_by", "created_at")
    inlines = [ReturnRecordInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(EquipmentHistory)
class EquipmentHistoryAdmin(admin.ModelAdmin):
    list_display = ("equipment", "kind", "field_name", "changed_by", "changed_at")
    list_filter = ("kind", "changed_at")
    search_fields = ("equipment__inventory_number", "equipment__name", "field_name")
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
    list_display = ("usage", "quantity", "returned_at", "condition", "processed_by")
    list_filter = ("condition", "returned_at")
    readonly_fields = (
        "usage",
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
