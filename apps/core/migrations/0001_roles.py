from django.db import migrations

# Названия групп совпадают с константами в apps/core/roles.py
GROUPS = ["Бухгалтерия", "СБ и юристы", "Администратор"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
