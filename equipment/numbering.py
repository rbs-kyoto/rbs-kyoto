import re

from django.core.exceptions import ValidationError
from django.utils import timezone


SERIAL_DIGITS = 6
MAX_SERIAL = 10**SERIAL_DIGITS - 1


def fiscal_year_code(day):
    """Return the last two digits of the fiscal year (April-March) of `day`."""
    fiscal_year = day.year if day.month >= 4 else day.year - 1
    return f"{fiscal_year % 100:02d}"


def generate_inventory_number(category_code, registered_on=None):
    """Build the next number as <category><fiscal yy><6-digit serial>, e.g. A-26000001."""
    from .models import Equipment

    registered_on = registered_on or timezone.localdate()
    prefix = f"{category_code}-{fiscal_year_code(registered_on)}"
    pattern = re.compile(re.escape(prefix) + rf"(\d{{{SERIAL_DIGITS}}})")
    last_serial = 0
    for number in Equipment.objects.filter(
        inventory_number__startswith=prefix
    ).values_list("inventory_number", flat=True):
        match = pattern.fullmatch(number)
        if match:
            last_serial = max(last_serial, int(match.group(1)))

    if last_serial >= MAX_SERIAL:
        raise ValidationError(
            "この分類・年度の備品番号は上限に達しています。"
        )
    return f"{prefix}{last_serial + 1:0{SERIAL_DIGITS}d}"
