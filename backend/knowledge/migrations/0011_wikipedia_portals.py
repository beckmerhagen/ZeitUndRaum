import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0010_assertion_v2")]

    operations = [
        migrations.CreateModel(
            name="WikipediaPortal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("language", models.CharField(max_length=24)),
                ("title", models.CharField(max_length=500)),
                ("url", models.URLField(max_length=1200)),
                ("page_id", models.BigIntegerField(blank=True, null=True)),
                ("revision_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "scan_status",
                    models.CharField(
                        choices=[
                            ("pending", "Ausstehend"),
                            ("running", "Wird ausgewertet"),
                            ("complete", "Abgeschlossen"),
                            ("partial", "Teilweise abgeschlossen"),
                            ("failed", "Fehlgeschlagen"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("article_count", models.PositiveIntegerField(default=0)),
                ("assertion_count", models.PositiveIntegerField(default=0)),
                ("last_scanned_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "subject_entity",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="wikipedia_portals",
                        to="knowledge.entity",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PortalArticle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=500)),
                ("url", models.URLField(max_length=1200)),
                ("page_id", models.BigIntegerField(blank=True, null=True)),
                ("revision_id", models.BigIntegerField(blank=True, null=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("active", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("assertions", models.ManyToManyField(blank=True, related_name="portal_discoveries", to="knowledge.assertion")),
                (
                    "portal",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="articles", to="knowledge.wikipediaportal"),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="portal_articles",
                        to="knowledge.source",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PortalScanRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ausstehend"),
                            ("running", "Wird ausgewertet"),
                            ("complete", "Abgeschlossen"),
                            ("partial", "Teilweise abgeschlossen"),
                            ("failed", "Fehlgeschlagen"),
                        ],
                        default="running",
                        max_length=16,
                    ),
                ),
                ("portal_revision_id", models.BigIntegerField(blank=True, null=True)),
                ("discovered_articles", models.PositiveIntegerField(default=0)),
                ("processed_articles", models.PositiveIntegerField(default=0)),
                ("discovered_assertions", models.PositiveIntegerField(default=0)),
                ("continuation", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "portal",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scan_runs", to="knowledge.wikipediaportal"),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="wikipediaportal",
            constraint=models.UniqueConstraint(fields=("language", "title"), name="unique_wikipedia_portal"),
        ),
        migrations.AddIndex(
            model_name="wikipediaportal",
            index=models.Index(fields=["language", "scan_status"], name="knowledge_w_languag_61dc7b_idx"),
        ),
        migrations.AddIndex(
            model_name="wikipediaportal",
            index=models.Index(fields=["last_scanned_at"], name="knowledge_w_last_sc_1cb4a5_idx"),
        ),
        migrations.AddConstraint(
            model_name="portalarticle",
            constraint=models.UniqueConstraint(fields=("portal", "title"), name="unique_portal_article"),
        ),
        migrations.AddIndex(
            model_name="portalarticle",
            index=models.Index(fields=["portal", "active", "position"], name="knowledge_p_portal__9d9001_idx"),
        ),
        migrations.AddIndex(
            model_name="portalscanrun",
            index=models.Index(fields=["portal", "started_at"], name="knowledge_p_portal__ce558c_idx"),
        ),
    ]
