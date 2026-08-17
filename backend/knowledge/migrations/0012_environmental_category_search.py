from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0011_wikipedia_portals")]

    operations = [
        migrations.AlterField(
            model_name="environmentalevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("volcano", "Vulkanausbruch"),
                    ("earthquake", "Erdbeben"),
                    ("storm_surge", "Sturmflut"),
                    ("drought", "Dürre"),
                    ("heatwave", "Hitzewelle"),
                    ("frost", "Frost / Kälteperiode"),
                    ("flood", "Hochwasser"),
                    ("river_course_change", "Flusslaufverlagerung"),
                    ("other", "Anderes Naturereignis"),
                ],
                max_length=24,
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
                    ("environment", "Naturereignis-Kategorie als Ausgangspunkt"),
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
                    ("environment", "Naturereignis-Kategorie"),
                ],
                default="auto",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="explorationcontext",
            name="environmental_event_types",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
