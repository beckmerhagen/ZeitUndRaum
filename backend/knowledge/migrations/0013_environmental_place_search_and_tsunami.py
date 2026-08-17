from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0012_environmental_category_search")]

    operations = [
        migrations.AlterField(
            model_name="environmentalevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("volcano", "Vulkanausbruch"),
                    ("earthquake", "Erdbeben"),
                    ("tsunami", "Tsunami"),
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
        migrations.AddField(
            model_name="explorationcontext",
            name="environmental_place_name",
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
