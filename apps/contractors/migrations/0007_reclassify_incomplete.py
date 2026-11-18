from django.db import migrations


def reclassify(apps, schema_editor):
    sessions = apps.get_model("contractors", "CheckSession")
    sessions.objects.filter(is_partial=True, status="safe").update(status="unknown")


class Migration(migrations.Migration):
    dependencies = [("contractors", "0006_incomplete_verdict")]
    operations = [migrations.RunPython(reclassify, migrations.RunPython.noop)]
