from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0009_migrate_category_strings_to_fk"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="news",
            name="category",
        ),
        migrations.RenameField(
            model_name="news",
            old_name="category_fk",
            new_name="category",
        ),
    ]
