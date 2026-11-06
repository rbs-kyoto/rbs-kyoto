from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("places", "0001_initial"),
        # 機材側の参照先を places.Place へ付け替えたあとに、列を追加する
        ("equipment", "0011_move_location_to_places"),
    ]

    operations = [
        migrations.AddField(
            model_name="place",
            name="is_storage",
            field=models.BooleanField(default=True, verbose_name="機材の保管場所として使う"),
        ),
        migrations.AddField(
            model_name="place",
            name="is_venue",
            field=models.BooleanField(default=False, verbose_name="予定の場所として使う"),
        ),
    ]
