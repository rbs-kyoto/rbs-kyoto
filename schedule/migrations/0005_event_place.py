"""予定の場所を、自由入力(location)から場所マスター(place)へ移す。

- 名前が1件だけ一致する場所があれば、その場所を紐付ける(その場所は「予定の場所」として使えるようにする)
- 一致しない・複数一致して決められないものは、メモ(description)の先頭に退避する
"""

from django.db import migrations, models
import django.db.models.deletion


def to_master(apps, schema_editor):
    Event = apps.get_model("schedule", "Event")
    Place = apps.get_model("places", "Place")

    for event in Event.objects.exclude(location=""):
        text = event.location.strip()
        matches = list(Place.objects.filter(name=text)[:2])
        if len(matches) == 1:
            place = matches[0]
            if not place.is_venue:
                place.is_venue = True
                place.save(update_fields=["is_venue"])
            event.place = place
        else:
            note = f"【場所】{text}"
            event.description = f"{note}\n{event.description}" if event.description else note
        event.save(update_fields=["place", "description"])


def to_text(apps, schema_editor):
    Event = apps.get_model("schedule", "Event")
    for event in Event.objects.exclude(place=None).select_related("place"):
        event.location = event.place.name
        event.save(update_fields=["location"])


class Migration(migrations.Migration):
    dependencies = [
        ("places", "0002_place_kinds"),
        ("schedule", "0004_attendance_reminder_delivery"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="place",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="schedule_events",
                to="places.place",
                verbose_name="場所",
            ),
        ),
        migrations.RunPython(to_master, to_text),
        migrations.RemoveField(model_name="event", name="location"),
    ]
