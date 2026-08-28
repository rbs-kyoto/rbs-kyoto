from django.db import migrations

from main.sanitizers import sanitize_richtext


def sanitize_existing_captions(apps, schema_editor):
    """保存時の無害化を入れる前に登録された本文を洗い直す。

    News.save() は今後の保存を守るが、すでに入っている本文には効かないため
    ここで一度だけ通す。
    """
    News = apps.get_model("main", "News")

    for pk, caption in News.objects.values_list("pk", "caption").iterator():
        cleaned = sanitize_richtext(caption)
        if cleaned != caption:
            News.objects.filter(pk=pk).update(caption=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0010_finalize_news_category"),
    ]

    operations = [
        # 取り除いたHTMLは復元できないため、巻き戻しは何もしない。
        migrations.RunPython(
            sanitize_existing_captions,
            migrations.RunPython.noop,
        ),
    ]
