import re
import string
from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone


DAILY_SUFFIXES = string.ascii_lowercase[:25]


def generate_inventory_number(category_code, registered_on=None):
    from .models import Equipment

    registered_on = registered_on or timezone.localdate()
    date_code = registered_on.strftime("%y%m%d")
    prefix = f"-621{date_code}"
    used_suffixes = set()

    for number in Equipment.objects.filter(
        inventory_number__contains=prefix
    ).values_list("inventory_number", flat=True):
        match = re.fullmatch(r"[A-Z]-621" + re.escape(date_code) + r"([a-y])", number)
        if match:
            used_suffixes.add(match.group(1))

    suffix = next((letter for letter in DAILY_SUFFIXES if letter not in used_suffixes), None)
    if suffix is None:
        raise ValidationError(
            "この日付の備品番号は上限の25件に達しています。翌日以降に登録してください。"
        )

    return f"{category_code}-621{date_code}{suffix}"
