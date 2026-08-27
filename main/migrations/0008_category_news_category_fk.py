from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0007_news_is_internal"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True, verbose_name="カテゴリ名")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="表示順")),
            ],
            options={
                "verbose_name": "Category",
                "verbose_name_plural": "Category",
                "ordering": ["order", "name"],
            },
        ),
        migrations.AddField(
            model_name="news",
            name="category_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="news",
                to="main.category",
                verbose_name="カテゴリ",
            ),
        ),
    ]
