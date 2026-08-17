from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0004_explorationcontext_query_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="explorationcontext",
            name="anchor_mode",
            field=models.CharField(
                choices=[("space", "Ort als Ausgangspunkt"), ("time", "Zeit als Ausgangspunkt")],
                default="space",
                max_length=16,
            ),
        ),
    ]
