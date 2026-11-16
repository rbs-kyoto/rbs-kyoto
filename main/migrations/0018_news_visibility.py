from django.db import migrations, models


def internal_to_visibility(apps, schema_editor):
    # これまでの「限定公開」は、いちばん狭い「部内のみ」に移す。
    # (広げすぎるより、狭くしておいて必要なものだけ後から広げるほうが安全なため)
    News = apps.get_model("main", "News")
    News.objects.filter(is_internal=True).update(visibility="club")


def visibility_to_internal(apps, schema_editor):
    News = apps.get_model("main", "News")
    News.objects.exclude(visibility="public").update(is_internal=True)


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0017_headerlogoschedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="news",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "校外まで(誰でも)"),
                    ("school", "部外まで(ログインした人)"),
                    ("club", "部内のみ(放送部員)"),
                ],
                default="public",
                max_length=10,
                verbose_name="公開範囲",
            ),
        ),
        migrations.RunPython(internal_to_visibility, visibility_to_internal),
        migrations.RemoveField(
            model_name="news",
            name="is_internal",
        ),
    ]
