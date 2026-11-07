import csv
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from roll.models import Position

from places.models import Place

from .models import Category, Equipment, EquipmentHistory, Manufacturer

MAX_ROWS = 2000
MAX_ERRORS = 20

EXPORT_HEADERS = [
    "備品番号",
    "備品名",
    "分類",
    "メーカー",
    "型番",
    "製造番号",
    "レシート番号",
    "保有数量",
    "単位",
    "管理担当役職",
    "保管場所",
    "購入日",
    "購入価格",
    "通貨",
    "購入先",
    "保証期限",
    "法定耐用年数",
    "備考",
    "備品の状態",
    "利用状況",
    "登録日時",
    "最終更新日時",
]

# CSV header -> internal key. 備品番号・利用状況・登録日時・最終更新日時 are
# reference columns that are exported but ignored on import.
HEADER_ALIASES = {
    "備品名": "name",
    "分類": "category",
    "メーカー": "manufacturer",
    "型番": "model_number",
    "製造番号": "serial_number",
    "レシート番号": "receipt_number",
    "保有数量": "quantity",
    "数量": "quantity",
    "単位": "unit",
    "管理担当役職": "manager",
    "管理担当者": "manager",
    "保管場所": "location",
    "購入日": "purchased_on",
    "購入価格": "purchase_price",
    "通貨": "purchase_currency",
    "購入先": "purchase_vendor",
    "保証期限": "warranty_expiry",
    "法定耐用年数": "expected_lifespan_years",
    "備考": "notes",
    "備品の状態": "condition",
}
REQUIRED_KEYS = {"name", "category", "quantity"}


class EquipmentImportError(Exception):
    pass


def export_row(item):
    return [
        item.inventory_number,
        item.name,
        str(item.category),
        str(item.manufacturer) if item.manufacturer else "",
        item.model_number,
        item.serial_number,
        item.receipt_number,
        item.quantity,
        item.unit,
        item.manager.name if item.manager else "",
        str(item.location) if item.location else "",
        item.purchased_on.isoformat() if item.purchased_on else "",
        int(item.purchase_price) if item.purchase_price is not None else "",
        item.purchase_currency,
        item.purchase_vendor,
        item.warranty_expiry.isoformat() if item.warranty_expiry else "",
        item.expected_lifespan_years if item.expected_lifespan_years is not None else "",
        item.notes,
        item.get_condition_display(),
        item.usage_status,
        timezone.localtime(item.created_at).strftime("%Y-%m-%d %H:%M"),
        timezone.localtime(item.updated_at).strftime("%Y-%m-%d %H:%M"),
    ]


def write_export(response, items):
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(EXPORT_HEADERS)
    for item in items:
        writer.writerow(export_row(item))


def _decode(uploaded_file):
    content = uploaded_file.read()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise EquipmentImportError("CSVの文字コードはUTF-8またはShift-JISにしてください。")


def _norm(value):
    return unicodedata.normalize("NFKC", value or "").strip()


def _parse_date(value):
    value = _norm(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("日付は YYYY-MM-DD 形式で入力してください")


def _parse_int(value, label, minimum):
    value = _norm(value).replace(",", "")
    if not value:
        return None
    if not value.isdecimal() or int(value) < minimum:
        raise ValueError(f"{label}は{minimum}以上の整数で入力してください")
    return int(value)


def _parse_price(value):
    value = _norm(value).replace(",", "").replace("¥", "").replace("円", "")
    if not value:
        return None
    try:
        price = Decimal(value)
    except InvalidOperation:
        raise ValueError("購入価格は数字で入力してください") from None
    if price < 0 or price != price.to_integral_value():
        raise ValueError("購入価格は0以上の整数で入力してください")
    return price


class _Lookups:
    def __init__(self):
        self.categories = {}
        for category in Category.objects.all():
            for key in (category.code, category.name, str(category)):
                self.categories[_norm(key).casefold()] = category
        self.locations = {}
        name_counts = {}
        active = list(Place.objects.filter(is_active=True, is_storage=True))
        for location in active:
            name_counts[location.name] = name_counts.get(location.name, 0) + 1
        for location in active:
            self.locations[_norm(str(location)).casefold()] = location
            if name_counts[location.name] == 1:
                self.locations.setdefault(_norm(location.name).casefold(), location)
        self.positions = {
            _norm(position.name).casefold(): position
            for position in Position.objects.filter(is_active=True)
        }
        self.currencies = {}
        for value, label in Equipment.Currency.choices:
            self.currencies[value.casefold()] = value
            self.currencies[label] = value
        self.conditions = {}
        for value, label in Equipment.Condition.choices:
            self.conditions[value] = value
            self.conditions[label] = value

    def manager(self, text):
        position = self.positions.get(_norm(text).casefold())
        if position is None:
            raise ValueError(f"管理担当役職「{text}」が役職に見つかりません")
        return position


def _parse_row(raw_row, lookups):
    row = {
        HEADER_ALIASES[header.strip()]: (value or "").strip()
        for header, value in raw_row.items()
        if header and header.strip() in HEADER_ALIASES
    }
    if not row.get("name"):
        raise ValueError("備品名が必要です")

    category = lookups.categories.get(_norm(row.get("category", "")).casefold())
    if category is None:
        raise ValueError(f"分類「{row.get('category', '')}」が見つかりません")

    quantity = _parse_int(row.get("quantity", ""), "保有数量", 1)
    if quantity is None:
        raise ValueError("保有数量が必要です")

    location = None
    if row.get("location"):
        location = lookups.locations.get(_norm(row["location"]).casefold())
        if location is None:
            raise ValueError(f"保管場所「{row['location']}」が見つかりません")

    manager = lookups.manager(row["manager"]) if row.get("manager") else None

    currency = Equipment.Currency.JPY
    if row.get("purchase_currency"):
        currency = lookups.currencies.get(_norm(row["purchase_currency"]).casefold()) or (
            lookups.currencies.get(row["purchase_currency"].strip())
        )
        if currency is None:
            raise ValueError(f"通貨「{row['purchase_currency']}」は無効です")

    condition = Equipment.Condition.NORMAL
    if row.get("condition"):
        condition = lookups.conditions.get(row["condition"].strip())
        if condition is None:
            raise ValueError(f"備品の状態「{row['condition']}」は無効です")

    manufacturer_name = " ".join(row.get("manufacturer", "").split())
    if len(manufacturer_name) > Manufacturer._meta.get_field("name").max_length:
        raise ValueError("メーカー名が長すぎます")

    equipment = Equipment(
        category=category,
        name=row["name"],
        model_number=row.get("model_number", ""),
        serial_number=row.get("serial_number", ""),
        receipt_number=row.get("receipt_number", ""),
        quantity=quantity,
        unit=row.get("unit") or "個",
        manager=manager,
        location=location,
        purchased_on=_parse_date(row.get("purchased_on", "")),
        purchase_price=_parse_price(row.get("purchase_price", "")),
        purchase_currency=currency,
        purchase_vendor=row.get("purchase_vendor", ""),
        warranty_expiry=_parse_date(row.get("warranty_expiry", "")),
        expected_lifespan_years=_parse_int(
            row.get("expected_lifespan_years", ""), "法定耐用年数", 0
        ),
        notes=row.get("notes", ""),
        condition=condition,
    )
    try:
        equipment.full_clean(
            exclude=[
                "inventory_number",
                "qr_inventory_number",
                "qr_token",
                "manufacturer",
                "created_by",
            ]
        )
    except ValidationError as error:
        messages = [m for msgs in error.message_dict.values() for m in msgs]
        raise ValueError(" / ".join(messages)) from None
    return equipment, manufacturer_name


def import_equipment_csv(uploaded_file, user):
    """Create new equipment from a CSV. All rows succeed or none are saved."""
    text = _decode(uploaded_file)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    keys = {
        HEADER_ALIASES[header.strip()]
        for header in (reader.fieldnames or [])
        if header and header.strip() in HEADER_ALIASES
    }
    missing = REQUIRED_KEYS - keys
    if missing:
        labels = {"name": "備品名", "category": "分類", "quantity": "保有数量"}
        raise EquipmentImportError(
            "CSVに次の列が必要です: "
            + "、".join(labels[key] for key in sorted(missing))
        )

    lookups = _Lookups()
    parsed, errors = [], []
    try:
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                errors.append(f"{row_number}行目: ヘッダーより多くの列が指定されています。")
            elif any(value and value.strip() for value in raw_row.values()):
                if len(parsed) + len(errors) >= MAX_ROWS:
                    raise EquipmentImportError(
                        f"一度にインポートできるのは{MAX_ROWS}行までです。"
                    )
                try:
                    parsed.append(_parse_row(raw_row, lookups))
                except ValueError as error:
                    errors.append(f"{row_number}行目: {error}")
            if len(errors) >= MAX_ERRORS:
                break
    except csv.Error as error:
        raise EquipmentImportError(f"CSVを読み取れません: {error}") from None
    if errors:
        raise EquipmentImportError("\n".join(errors))
    if not parsed:
        raise EquipmentImportError("CSVにインポートするデータがありません。")

    manufacturers = {}
    try:
        with transaction.atomic():
            for equipment, manufacturer_name in parsed:
                if manufacturer_name:
                    key = manufacturer_name.casefold()
                    if key not in manufacturers:
                        manufacturers[key] = (
                            Manufacturer.objects.filter(name__iexact=manufacturer_name).first()
                            or Manufacturer.objects.create(name=manufacturer_name)
                        )
                    equipment.manufacturer = manufacturers[key]
                equipment.created_by = user
                equipment.last_modified_by = user
                equipment.save()
                EquipmentHistory.objects.create(
                    equipment=equipment,
                    changed_by=user,
                    field_name="登録",
                    new_value=f"{equipment.inventory_number} {equipment.name}（CSVインポート）",
                )
    except ValidationError as error:
        raise EquipmentImportError("; ".join(error.messages)) from None
    except IntegrityError:
        raise EquipmentImportError(
            "備品番号を確保できませんでした。もう一度インポートしてください。"
        ) from None
    return len(parsed)
