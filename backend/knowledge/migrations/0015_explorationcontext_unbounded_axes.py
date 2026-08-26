from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0014_alter_entity_kind_historicalprocess_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="explorationcontext",
            name="space_unbounded",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="explorationcontext",
            name="time_unbounded",
            field=models.BooleanField(default=False),
        ),
    ]
