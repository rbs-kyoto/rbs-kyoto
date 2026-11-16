from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .models import (
    Category,
    Equipment,
    Manufacturer,
    QRDesign,
    ReturnRecord,
    UsageRecord,
)
from . import help_texts
from .numbering import generate_inventory_number
from places.models import Place
from roll.models import Position, RosterEntry


class InfoTextMixin:
    """Attach the explanation shown behind each field's "i" button."""

    info_texts = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.info_text = self.info_texts.get(name, "")


class EquipmentForm(InfoTextMixin, forms.ModelForm):
    info_texts = help_texts.EQUIPMENT

    new_manufacturer = forms.CharField(
        label="新しいメーカーを追加",
        max_length=100,
        required=False,
        help_text="一覧にないメーカーのみ入力してください。入力すると上の選択より優先されます。",
    )

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
        self.fields["manager"].queryset = Position.objects.filter(is_active=True)
        self.fields["location"].queryset = Place.objects.filter(
            is_active=True, is_storage=True
        )
        self.fields["location"].required = False
        self.fields["manufacturer"].queryset = Manufacturer.objects.all()
        self.fields["manufacturer"].empty_label = "---------"
        self.order_fields([*self.Meta.fields, "new_manufacturer"])

    def clean_new_manufacturer(self):
        return " ".join(self.cleaned_data["new_manufacturer"].split())

    def clean(self):
        cleaned_data = super().clean()
        new_name = cleaned_data.get("new_manufacturer")
        if new_name:
            cleaned_data["manufacturer"] = (
                Manufacturer.objects.filter(name__iexact=new_name).first()
                or Manufacturer(name=new_name)
            )
        if not self.instance.pk:
            category = cleaned_data.get("category")
            if category:
                try:
                    self.generated_inventory_number = generate_inventory_number(
                        category.code
                    )
                except ValidationError as error:
                    self.add_error("category", error)
        return cleaned_data

    def save(self, commit=True):
        equipment = super().save(commit=False)
        if not self.instance.pk and hasattr(self, "generated_inventory_number"):
            equipment.inventory_number = self.generated_inventory_number
        manufacturer = self.cleaned_data.get("manufacturer")
        if manufacturer is not None and manufacturer.pk is None:
            manufacturer, _ = Manufacturer.objects.get_or_create(
                name=manufacturer.name
            )
        equipment.manufacturer = manufacturer
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


class UsageRecordForm(InfoTextMixin, forms.ModelForm):
    info_texts = help_texts.USAGE

    destination_selection = forms.ChoiceField(
        label="貸出・持出先",
        choices=(),
    )
    other_destination = forms.CharField(
        label="その他の貸出・持出先",
        max_length=200,
        required=False,
        help_text="貸出・持出先で「その他」を選択した場合に入力してください。",
    )

    class Meta:
        model = UsageRecord
        fields = [
            "equipment",
            "usage_type",
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
        self.order_fields(
            [
                "equipment",
                "usage_type",
                "destination_selection",
                "other_destination",
                "responsible_person",
                "recipient",
                "quantity",
                "started_at",
                "due_at",
                "purpose",
                "notes",
            ]
        )
        self.fields["equipment"].queryset = Equipment.objects.filter(is_active=True)
        self.fields["responsible_person"].queryset = RosterEntry.objects.exclude(
            entry_type=RosterEntry.EntryType.ORGANIZATION
        ).order_by("name")
        destination_entries = RosterEntry.objects.order_by(
            "entry_type",
            "grade",
            "homeroom",
            "student_number",
            "name_kana",
            "name",
        )
        self.fields["destination_selection"].choices = [
            ("", "---------"),
            *[(str(entry.pk), str(entry)) for entry in destination_entries],
            ("other", "その他"),
        ]
        self.fields["due_at"].required = False

    def clean(self):
        cleaned_data = super().clean()
        started_at = cleaned_data.get("started_at")
        due_at = cleaned_data.get("due_at")
        if started_at and due_at and due_at < started_at:
            self.add_error("due_at", "返却予定日時は開始日時以降を指定してください。")
        selection = cleaned_data.get("destination_selection")
        if selection == "other":
            other_destination = cleaned_data.get("other_destination", "").strip()
            if not other_destination:
                self.add_error(
                    "other_destination",
                    "その他の貸出・持出先を入力してください。",
                )
            cleaned_data["destination_entry"] = None
            cleaned_data["destination"] = other_destination
        elif selection:
            destination_entry = RosterEntry.objects.filter(pk=selection).first()
            if destination_entry is None:
                self.add_error("destination_selection", "名簿から貸出・持出先を選択してください。")
            else:
                cleaned_data["destination_entry"] = destination_entry
                cleaned_data["destination"] = str(destination_entry)
        return cleaned_data

    def save(self, commit=True):
        usage = super().save(commit=False)
        usage.destination_entry = self.cleaned_data.get("destination_entry")
        usage.destination = self.cleaned_data["destination"]
        if commit:
            usage.save()
            self.save_m2m()
        return usage


class ReturnRecordForm(InfoTextMixin, forms.ModelForm):
    info_texts = help_texts.RETURN

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


class StorageLocationForm(InfoTextMixin, forms.ModelForm):
    info_texts = help_texts.LOCATION

    class Meta:
        model = Place
        fields = ["name", "code", "parent", "description", "notes", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Place.objects.filter(is_active=True)
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


class QRDesignForm(InfoTextMixin, forms.ModelForm):
    info_texts = help_texts.QR_DESIGN

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


class EquipmentImportForm(InfoTextMixin, forms.Form):
    info_texts = help_texts.IMPORT

    csv_file = forms.FileField(
        label="CSVファイル",
        help_text="UTF-8またはShift-JIS形式、10MB以下。",
    )

    def clean_csv_file(self):
        uploaded_file = self.cleaned_data["csv_file"]
        if not uploaded_file.name.lower().endswith(".csv"):
            raise forms.ValidationError("拡張子が.csvのファイルを選択してください。")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("CSVファイルは10MB以下にしてください。")
        return uploaded_file
