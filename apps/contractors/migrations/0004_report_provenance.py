from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contractors", "0003_okved")]
    operations = [
        migrations.AddField("checksession", "scoring_config", models.JSONField(blank=True, default=dict, verbose_name="Параметры оценки")),
        migrations.AddField("checksession", "is_demo", models.BooleanField(default=False, verbose_name="Демонстрационные данные")),
        migrations.AddField("sourcedata", "mode", models.CharField(default="unknown", max_length=10, verbose_name="Режим источника")),
        migrations.AddField("sourcedata", "error", models.TextField(blank=True, verbose_name="Причина недоступности")),
    ]
