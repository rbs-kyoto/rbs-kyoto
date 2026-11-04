from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .models import (
    Category,
    Equipment,
    QRDesign,
    ReturnRecord,
    StorageLocation,
    UsageRecord,
)
from .numbering import generate_inventory_number
from roll.models import RosterEntry


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = [
            "category",
            "name",
            "manufacturer",
            "model_number",
            "serial_number",
            "receipt_number",
            "quantity",
            "unit",
            "manager",
            "location",
            "purchased_on",
            "purchase_price",
            "purchase_currency",
            "purchase_vendor",
            "warranty_expiry",
            "expected_lifespan_years",
            "notes",
            "image",
            "condition",
        ]
        widgets = {
            "purchased_on": forms.DateInput(attrs={"type": "date"}),
            "warranty_expiry": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["category"].queryset = Category.objects.all()
        self.fields["manager"].queryset = RosterEntry.objects.exclude(
            entry_type=RosterEntry.EntryType.ORGANIZATION
        ).order_by("name")
        self.fields["location"].queryset = StorageLocation.objects.filter(
            is_active=True
        )
        self.fields["location"].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not self.instance.pk:
            category = cleaned_data.get("category")
            if category:
                try:
                    self.generated_inventory_number = generate_inventory_number(
                        category.code,
                        cleaned_data.get("purchased_on"),
                    )
                except ValidationError as error:
                    self.add_error("category", error)
        return cleaned_data

    def save(self, commit=True):
        equipment = super().save(commit=False)
        if not self.instance.pk and hasattr(self, "generated_inventory_number"):
            equipment.inventory_number = self.generated_inventory_number
        if commit:
            equipment.save()
            self.save_m2m()
        return equipment

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if self.instance.pk:
            committed = (
                self.instance.outstanding_quantity
                + self.instance.unavailable_return_quantity
            )
            if quantity < committed:
                raise forms.ValidationError(
                    f"貸出中・使用不可の数量（{committed}）を下回る数量には変更できません。"
                )
        return quantity


class UsageRecordForm(forms.ModelForm):
    class Meta:
        model = UsageRecord
        fields = [
            "equipment",
            "usage_type",
            "destination",
            "responsible_person",
            "recipient",
            "quantity",
            "started_at",
            "due_at",
            "purpose",
            "notes",
        ]
        widgets = {
            "started_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "due_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(is_active=True)
        self.fields["responsible_person"].queryset = RosterEntry.objects.exclude(
            entry_type=RosterEntry.EntryType.ORGANIZATION
        ).order_by("name")
        self.fields["due_at"].required = False

    def clean(self):
        cleaned_data = super().clean()
        started_at = cleaned_data.get("started_at")
        due_at = cleaned_data.get("due_at")
        if started_at and due_at and due_at < started_at:
            self.add_error("due_at", "返却予定日時は開始日時以降を指定してください。")
        return cleaned_data


class ReturnRecordForm(forms.ModelForm):
    class Meta:
        model = ReturnRecord
        fields = [
            "quantity",
            "returned_at",
            "confirmed_by",
            "condition",
            "condition_details",
            "notes",
        ]
        widgets = {
            "returned_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "condition_details": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class StorageLocationForm(forms.ModelForm):
    class Meta:
        model = StorageLocation
        fields = ["name", "code", "parent", "description", "notes", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = StorageLocation.objects.filter(is_active=True)
        self.fields["parent"].required = False
        if self.instance.pk:
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(
                pk=self.instance.pk
            )

    def clean_parent(self):
        parent = self.cleaned_data["parent"]
        ancestor = parent
        while ancestor:
            if ancestor.pk == self.instance.pk:
                raise forms.ValidationError("自分自身を上位保管場所には指定できません。")
            ancestor = ancestor.parent
        return parent


class QRDesignForm(forms.ModelForm):
    color_validator = RegexValidator(
        regex=r"^#[0-9a-fA-F]{6}$",
        message="色は #RRGGBB 形式で入力してください。",
    )
    foreground = forms.CharField(
        label="前景色",
        validators=[color_validator],
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    background = forms.CharField(
        label="背景色",
        validators=[color_validator],
        widget=forms.TextInput(attrs={"type": "color"}),
    )

    class Meta:
        model = QRDesign
        fields = ["foreground", "background", "box_size", "border"]
        widgets = {
            "box_size": forms.NumberInput(attrs={"min": 2, "max": 20}),
            "border": forms.NumberInput(attrs={"min": 2, "max": 10}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("foreground") == cleaned_data.get("background"):
            raise forms.ValidationError("前景色と背景色は異なる色にしてください。")
        if cleaned_data.get("box_size", 0) not in range(2, 21):
            self.add_error("box_size", "出力サイズは2〜20の範囲で指定してください。")
        if cleaned_data.get("border", 0) not in range(2, 11):
            self.add_error("border", "余白は2〜10の範囲で指定してください。")
        return cleaned_data
