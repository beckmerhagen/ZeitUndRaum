from django.db import migrations, models
from django.db.models import Q
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0015_explorationcontext_unbounded_axes")]

    operations = [
        migrations.AddField(
            model_name="explorationcontext",
            name="time_from_year",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="explorationcontext",
            name="time_to_year",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="explorationcontext",
            name="context_radius_range",
        ),
        migrations.AlterField(
            model_name="explorationcontext",
            name="radius_km",
            field=models.PositiveIntegerField(
                default=25,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(20000),
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="explorationcontext",
            constraint=models.CheckConstraint(
                condition=Q(radius_km__gte=0, radius_km__lte=20000),
                name="context_radius_range",
            ),
        ),
    ]
