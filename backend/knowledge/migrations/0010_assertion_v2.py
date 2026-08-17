import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
import knowledge.models
import uuid
from django.db import migrations, models


def classify_existing_assertions(apps, schema_editor):
    Assertion = apps.get_model("knowledge", "Assertion")
    Source = apps.get_model("knowledge", "Source")
    Evidence = apps.get_model("knowledge", "Evidence")

    Assertion.objects.filter(time_start_year__isnull=False, time_end_year__isnull=False).update(
        temporal_scope="bounded"
    )
    Assertion.objects.filter(time_start_year__isnull=False, time_end_year__isnull=True).update(
        temporal_scope="open_end"
    )
    Assertion.objects.filter(time_start_year__isnull=True, time_end_year__isnull=False).update(
        temporal_scope="open_start"
    )
    Assertion.objects.filter(location__isnull=False).update(spatial_scope="point")

    Assertion.objects.filter(extraction_method__startswith="manual").update(
        knowledge_type="documented",
        confidence_reason="Manuell erfasste Aussage; Vertrauenswert aus der vorhandenen Evidenz übernommen.",
    )
    Assertion.objects.filter(extraction_method__startswith="curated").update(
        knowledge_type="documented",
        confidence_reason="Redaktionell kuratierte Aussage; Vertrauenswert aus der vorhandenen Evidenz übernommen.",
    )
    Assertion.objects.exclude(
        extraction_method__startswith="manual"
    ).exclude(
        extraction_method__startswith="curated"
    ).update(
        knowledge_type="automatic_extraction",
        confidence_reason="Automatisch extrahiert; Vertrauenswert aus Extraktionsmethode und vorhandener Evidenz übernommen.",
    )
    Assertion.objects.filter(status="disputed").update(
        confidence_reason="Widersprüchliche Evidenz im übernommenen Wissensbestand."
    )
    Assertion.objects.filter(status="rejected").update(
        confidence_reason="Bei der Qualitätsprüfung als unzutreffend oder nicht ausreichend belegt verworfen."
    )
    Source.objects.filter(license_name="").update(
        license_name="Nicht angegeben – Rechte an der Originalquelle prüfen"
    )
    Evidence.objects.filter(locator="").update(locator="Nicht näher bezeichnete Fundstelle")


class Migration(migrations.Migration):
    # PostgreSQL must commit the bulk classification before it can build the
    # new indexes. Each schema operation remains transactional; the data
    # migration itself is wrapped explicitly below.
    atomic = False

    dependencies = [("knowledge", "0009_global_environment_catalog")]

    operations = [
        migrations.AddField(
            model_name="assertion",
            name="calendar_model",
            field=models.CharField(
                choices=[
                    ("gregorian", "Gregorianisch"),
                    ("julian", "Julianisch"),
                    ("proleptic_gregorian", "Proleptisch gregorianisch"),
                    ("other", "Anderes Kalendersystem"),
                    ("unknown", "Unbekannt"),
                ],
                default="unknown",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="assertion",
            name="confidence_reason",
            field=models.TextField(default=knowledge.models.default_confidence_reason),
        ),
        migrations.AddField(
            model_name="assertion",
            name="knowledge_type",
            field=models.CharField(
                choices=[
                    ("documented", "Dokumentiert"),
                    ("reconstructed", "Rekonstruiert"),
                    ("scholarly_interpretation", "Wissenschaftlich eingeordnet"),
                    ("automatic_extraction", "Automatisch extrahiert"),
                ],
                default="automatic_extraction",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="assertion",
            name="location_entity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="located_assertions",
                to="knowledge.entity",
            ),
        ),
        migrations.AddField(
            model_name="assertion",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="assertion",
            name="spatial_extent",
            field=django.contrib.gis.db.models.fields.GeometryField(
                blank=True, geography=True, null=True, srid=4326
            ),
        ),
        migrations.AddField(
            model_name="assertion",
            name="spatial_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="assertion",
            name="spatial_scope",
            field=models.CharField(
                choices=[
                    ("point", "Punkt"),
                    ("feature", "Räumliches Objekt"),
                    ("region", "Region"),
                    ("global", "Global"),
                    ("unknown", "Raumbezug unbekannt"),
                ],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(model_name="assertion", name="temporal_note", field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="assertion",
            name="temporal_scope",
            field=models.CharField(
                choices=[
                    ("bounded", "Begrenzter Zeitraum"),
                    ("open_start", "Offener Beginn"),
                    ("open_end", "Offenes Ende"),
                    ("timeless", "Zeitunabhängig"),
                    ("unknown", "Zeit unbekannt"),
                ],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(model_name="assertion", name="time_end_day", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="assertion", name="time_end_month", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="assertion", name="time_start_day", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="assertion", name="time_start_month", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(
            model_name="assertion",
            name="value_max",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="assertion",
            name="value_min",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
        migrations.AddField(model_name="assertion", name="value_unit", field=models.CharField(blank=True, max_length=80)),
        migrations.AlterField(
            model_name="evidence",
            name="locator",
            field=models.CharField(default="Nicht näher bezeichnete Fundstelle", max_length=500),
        ),
        migrations.AlterField(
            model_name="source",
            name="license_name",
            field=models.CharField(
                default="Nicht angegeben – Rechte an der Originalquelle prüfen",
                max_length=200,
            ),
        ),
        migrations.RunPython(
            classify_existing_assertions,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AddIndex(
            model_name="assertion",
            index=models.Index(fields=["knowledge_type", "status"], name="knowledge_a_knowled_95e70b_idx"),
        ),
        migrations.AddIndex(
            model_name="assertion",
            index=models.Index(fields=["temporal_scope", "spatial_scope"], name="knowledge_a_tempora_fe36c5_idx"),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(object_entity__isnull=False) | ~models.Q(value_text="") | models.Q(value_number__isnull=False),
                name="assertion_value_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(time_start_year__isnull=True)
                | models.Q(time_end_year__isnull=True)
                | models.Q(time_start_year__lte=models.F("time_end_year")),
                name="assertion_time_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(time_start_month__isnull=True) | models.Q(time_start_month__gte=1, time_start_month__lte=12),
                name="assertion_start_month_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(time_end_month__isnull=True) | models.Q(time_end_month__gte=1, time_end_month__lte=12),
                name="assertion_end_month_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(time_start_day__isnull=True) | models.Q(time_start_day__gte=1, time_start_day__lte=31),
                name="assertion_start_day_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(
                condition=models.Q(time_end_day__isnull=True) | models.Q(time_end_day__gte=1, time_end_day__lte=31),
                name="assertion_end_day_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="assertion",
            constraint=models.CheckConstraint(condition=~models.Q(confidence_reason=""), name="assertion_confidence_reason_required"),
        ),
        migrations.AddConstraint(
            model_name="evidence",
            constraint=models.CheckConstraint(condition=~models.Q(locator=""), name="evidence_locator_required"),
        ),
        migrations.AddConstraint(
            model_name="source",
            constraint=models.CheckConstraint(condition=~models.Q(license_name=""), name="source_license_name_required"),
        ),
        migrations.CreateModel(
            name="AssertionRelation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("relation_type", models.CharField(choices=[("causes", "Verursacht"), ("contributes_to", "Trägt bei zu"), ("influences", "Beeinflusst"), ("part_of", "Ist Teil von"), ("reaction_to", "Ist Reaktion auf"), ("similar_to", "Ähnelt"), ("contemporary_with", "Ist gleichzeitig mit"), ("supports", "Stützt"), ("contradicts", "Widerspricht"), ("spatial_overlap", "Räumliche Überschneidung")], max_length=32)),
                ("evidence_level", models.CharField(choices=[("documented", "Belegter Zusammenhang"), ("scholarly_plausible", "Wissenschaftlich plausible Einordnung"), ("algorithmic_similarity", "Automatisch erkannte Ähnlichkeit"), ("coincidence", "Bloße Gleichzeitigkeit")], max_length=32)),
                ("summary", models.TextField()),
                ("mechanism", models.TextField(blank=True)),
                ("confidence", models.DecimalField(decimal_places=3, max_digits=4, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)])),
                ("confidence_reason", models.TextField()),
                ("temporal_overlap_years", models.BigIntegerField(blank=True, null=True)),
                ("spatial_distance_meters", models.PositiveBigIntegerField(blank=True, null=True)),
                ("extraction_method", models.CharField(default="manual", max_length=120)),
                ("algorithm_name", models.CharField(blank=True, max_length=160)),
                ("algorithm_version", models.CharField(blank=True, max_length=80)),
                ("status", models.CharField(choices=[("candidate", "Automatisch gefunden"), ("verified", "Belegt"), ("disputed", "Widersprüchlich"), ("rejected", "Verworfen")], default="candidate", max_length=16)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("evidence", models.ManyToManyField(blank=True, related_name="assertion_relations", to="knowledge.evidence")),
                ("source_assertion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="outgoing_relations", to="knowledge.assertion")),
                ("target_assertion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incoming_relations", to="knowledge.assertion")),
            ],
        ),
        migrations.AddIndex(
            model_name="assertionrelation",
            index=models.Index(fields=["relation_type", "evidence_level"], name="knowledge_a_relatio_feb25b_idx"),
        ),
        migrations.AddIndex(
            model_name="assertionrelation",
            index=models.Index(fields=["status", "confidence"], name="knowledge_a_status_e1ec19_idx"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.UniqueConstraint(fields=("source_assertion", "target_assertion", "relation_type", "evidence_level"), name="unique_assertion_relation"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.CheckConstraint(condition=~models.Q(source_assertion=models.F("target_assertion")), name="assertion_relation_distinct_assertions"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.CheckConstraint(condition=~models.Q(summary=""), name="assertion_relation_summary_required"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.CheckConstraint(condition=~models.Q(confidence_reason=""), name="assertion_relation_confidence_reason_required"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.CheckConstraint(condition=~models.Q(evidence_level="coincidence") | models.Q(relation_type="contemporary_with"), name="coincidence_is_only_contemporary"),
        ),
        migrations.AddConstraint(
            model_name="assertionrelation",
            constraint=models.CheckConstraint(condition=~models.Q(evidence_level="algorithmic_similarity") | models.Q(relation_type="similar_to"), name="algorithmic_similarity_relation_type"),
        ),
    ]
