from django.db import migrations, models

CAPTION_FIELD = models.CharField(
    blank=True, max_length=100, verbose_name="キャッチコピー"
)


def _caption_column_exists(schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(
            cursor, "main_pickup"
        )
    return any(column.name == "caption" for column in columns)


def add_caption_if_missing(apps, schema_editor):
    """#17 は同じ caption 列を作るマイグレーションを含んだままrevertされた。

    すでに適用済みの環境には列だけが残っているため、素直に AddField すると
    duplicate column で落ちる。列の定義は #17 のものと完全に同一なので、
    存在する場合は DB を触らず状態だけ揃えれば足りる。
    """
    if _caption_column_exists(schema_editor):
        return

    field = CAPTION_FIELD.clone()
    field.set_attributes_from_name("caption")
    schema_editor.add_field(apps.get_model("main", "Pickup"), field)


def remove_caption(apps, schema_editor):
    if not _caption_column_exists(schema_editor):
        return

    field = CAPTION_FIELD.clone()
    field.set_attributes_from_name("caption")
    schema_editor.remove_field(apps.get_model("main", "Pickup"), field)


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0010_finalize_news_category"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="pickup",
                    name="caption",
                    field=CAPTION_FIELD.clone(),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_caption_if_missing, remove_caption),
            ],
        ),
    ]
