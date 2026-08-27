from django.db import migrations


def migrate_categories_forward(apps, schema_editor):
    News = apps.get_model("main", "News")
    Category = apps.get_model("main", "Category")

    names = (
        News.objects.exclude(category="")
        .order_by("category")
        .values_list("category", flat=True)
        .distinct()
    )
    category_by_name = {}
    for order, name in enumerate(names):
        category, _ = Category.objects.get_or_create(name=name, defaults={"order": order})
        category_by_name[name] = category

    for news in News.objects.exclude(category=""):
        news.category_fk = category_by_name[news.category]
        news.save(update_fields=["category_fk"])


def migrate_categories_backward(apps, schema_editor):
    News = apps.get_model("main", "News")

    for news in News.objects.exclude(category_fk=None):
        news.category = news.category_fk.name
        news.save(update_fields=["category"])


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0008_category_news_category_fk"),
    ]

    operations = [
        migrations.RunPython(migrate_categories_forward, migrate_categories_backward),
    ]
