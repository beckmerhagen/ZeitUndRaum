import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0005_explorationcontext_anchor_mode")]

    operations = [
        migrations.AddField(
            model_name="explorationcontext",
            name="event_end_year",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="explorationcontext",
            name="event_start_year",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="explorationcontext",
            name="focus_entity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="focused_exploration_contexts",
                to="knowledge.entity",
            ),
        ),
        migrations.AlterField(
            model_name="explorationcontext",
            name="anchor_mode",
            field=models.CharField(
                choices=[
                    ("space", "Ort als Ausgangspunkt"),
                    ("event", "Ereignis als Ausgangspunkt"),
                    ("time", "Zeit als Ausgangspunkt"),
                ],
                default="space",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="explorationcontext",
            name="query_mode",
            field=models.CharField(
                choices=[
                    ("auto", "Automatisch erkennen"),
                    ("place", "Ort"),
                    ("event", "Ereignis"),
                    ("topic", "Thema"),
                ],
                default="auto",
                max_length=16,
            ),
        ),
    ]
