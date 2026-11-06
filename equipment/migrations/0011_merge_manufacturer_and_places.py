from django.db import migrations


class Migration(migrations.Migration):
    """Merge the two 0011 branches (メーカーのマスタ化 / 保管場所のPlace移行)."""

    dependencies = [
        ("equipment", "0011_manufacturer"),
        ("equipment", "0011_move_location_to_places"),
    ]

    operations = []
