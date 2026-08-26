import uuid

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator


def default_research_languages():
    return ["de", "en"]


def default_exploration_center():
    return "POINT (9.489 53.836)"


def default_confidence_reason():
    return "Automatisch erzeugte oder noch nicht individuell begründete Bewertung."


class Entity(models.Model):
    class Kind(models.TextChoices):
        PLACE = "place", "Ort"
        BUILDING = "building", "Bauwerk"
        PERSON = "person", "Person"
        ORGANIZATION = "organization", "Organisation"
        POLITY = "polity", "Herrschaftsgebiet"
        EVENT = "event", "Ereignis"
        MOVEMENT = "movement", "Bewegung"
        PROCESS = "process", "Historischer Prozess"
        NATURAL_FEATURE = "natural_feature", "Naturraum"
        OTHER = "other", "Sonstiges"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    canonical_name = models.CharField(max_length=300)
    labels = models.JSONField(default=dict, blank=True)
    descriptions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "entities"
        indexes = [models.Index(fields=["canonical_name"]), models.Index(fields=["kind"])]

    def __str__(self):
        return self.canonical_name


class ExternalIdentifier(models.Model):
    entity = models.ForeignKey(Entity, related_name="external_identifiers", on_delete=models.CASCADE)
    provider = models.CharField(max_length=80)
    external_id = models.CharField(max_length=500)
    url = models.URLField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"], name="unique_external_identifier")
        ]


class PlaceGeometry(models.Model):
    entity = models.ForeignKey(Entity, related_name="geometries", on_delete=models.CASCADE)
    geometry = models.GeometryField(srid=4326, geography=True)
    valid_from_year = models.BigIntegerField(null=True, blank=True)
    valid_to_year = models.BigIntegerField(null=True, blank=True)
    spatial_precision_meters = models.PositiveIntegerField(default=100)
    label = models.CharField(max_length=300, blank=True)
    is_reconstruction = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["valid_from_year", "valid_to_year"])]


class Source(models.Model):
    class Type(models.TextChoices):
        PRIMARY = "primary", "Primärquelle"
        SCHOLARLY = "scholarly", "Wissenschaft"
        INSTITUTION = "institution", "Institution"
        ENCYCLOPEDIA = "encyclopedia", "Enzyklopädie"
        COMMUNITY = "community", "Community"
        USER = "user", "Benutzerhinweis"

    provider = models.CharField(max_length=160)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1200)
    record_id = models.CharField(max_length=500, blank=True)
    source_type = models.CharField(max_length=24, choices=Type.choices, default=Type.ENCYCLOPEDIA)
    language = models.CharField(max_length=24, default="de")
    license_name = models.CharField(
        max_length=200,
        default="Nicht angegeben – Rechte an der Originalquelle prüfen",
    )
    license_url = models.URLField(max_length=1200, blank=True)
    publisher = models.CharField(max_length=300, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    retrieved_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "record_id", "url"], name="unique_source_record"),
            models.CheckConstraint(condition=~models.Q(license_name=""), name="source_license_name_required"),
        ]
        indexes = [models.Index(fields=["provider", "source_type"])]

    def __str__(self):
        return f"{self.provider}: {self.title}"


class Assertion(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Automatisch gefunden"
        VERIFIED = "verified", "Belegt"
        DISPUTED = "disputed", "Widersprüchlich"
        REJECTED = "rejected", "Verworfen"

    class Precision(models.TextChoices):
        DAY = "day", "Tag"
        MONTH = "month", "Monat"
        YEAR = "year", "Jahr"
        DECADE = "decade", "Jahrzehnt"
        CENTURY = "century", "Jahrhundert"
        RANGE = "range", "Zeitraum"
        UNKNOWN = "unknown", "Unbekannt"

    class KnowledgeType(models.TextChoices):
        DOCUMENTED = "documented", "Dokumentiert"
        RECONSTRUCTED = "reconstructed", "Rekonstruiert"
        SCHOLARLY_INTERPRETATION = "scholarly_interpretation", "Wissenschaftlich eingeordnet"
        AUTOMATIC_EXTRACTION = "automatic_extraction", "Automatisch extrahiert"

    class TemporalScope(models.TextChoices):
        BOUNDED = "bounded", "Begrenzter Zeitraum"
        OPEN_START = "open_start", "Offener Beginn"
        OPEN_END = "open_end", "Offenes Ende"
        TIMELESS = "timeless", "Zeitunabhängig"
        UNKNOWN = "unknown", "Zeit unbekannt"

    class CalendarModel(models.TextChoices):
        GREGORIAN = "gregorian", "Gregorianisch"
        JULIAN = "julian", "Julianisch"
        PROLEPTIC_GREGORIAN = "proleptic_gregorian", "Proleptisch gregorianisch"
        OTHER = "other", "Anderes Kalendersystem"
        UNKNOWN = "unknown", "Unbekannt"

    class SpatialScope(models.TextChoices):
        POINT = "point", "Punkt"
        FEATURE = "feature", "Räumliches Objekt"
        REGION = "region", "Region"
        GLOBAL = "global", "Global"
        UNKNOWN = "unknown", "Raumbezug unbekannt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Entity, related_name="assertions", on_delete=models.CASCADE)
    predicate = models.SlugField(max_length=120)
    object_entity = models.ForeignKey(Entity, related_name="incoming_assertions", null=True, blank=True, on_delete=models.SET_NULL)
    value_text = models.TextField(blank=True)
    value_number = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    value_unit = models.CharField(max_length=80, blank=True)
    value_min = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    value_max = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    time_start_year = models.BigIntegerField(null=True, blank=True)
    time_end_year = models.BigIntegerField(null=True, blank=True, help_text="Inklusives Endjahr")
    time_start_month = models.PositiveSmallIntegerField(null=True, blank=True)
    time_start_day = models.PositiveSmallIntegerField(null=True, blank=True)
    time_end_month = models.PositiveSmallIntegerField(null=True, blank=True)
    time_end_day = models.PositiveSmallIntegerField(null=True, blank=True)
    time_precision = models.CharField(max_length=16, choices=Precision.choices, default=Precision.UNKNOWN)
    temporal_uncertainty_years = models.PositiveBigIntegerField(default=0)
    temporal_scope = models.CharField(max_length=16, choices=TemporalScope.choices, default=TemporalScope.UNKNOWN)
    calendar_model = models.CharField(max_length=24, choices=CalendarModel.choices, default=CalendarModel.UNKNOWN)
    temporal_note = models.TextField(blank=True)
    location = models.PointField(srid=4326, geography=True, null=True, blank=True)
    location_entity = models.ForeignKey(
        Entity,
        related_name="located_assertions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    spatial_extent = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_scope = models.CharField(max_length=16, choices=SpatialScope.choices, default=SpatialScope.UNKNOWN)
    spatial_precision_meters = models.PositiveIntegerField(null=True, blank=True)
    spatial_note = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CANDIDATE)
    knowledge_type = models.CharField(
        max_length=32,
        choices=KnowledgeType.choices,
        default=KnowledgeType.AUTOMATIC_EXTRACTION,
    )
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confidence_reason = models.TextField(default=default_confidence_reason)
    extraction_method = models.CharField(max_length=120, default="manual")
    metadata = models.JSONField(default=dict, blank=True)
    fingerprint = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["predicate", "status"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
            models.Index(fields=["confidence"]),
            models.Index(fields=["knowledge_type", "status"]),
            models.Index(fields=["temporal_scope", "spatial_scope"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(object_entity__isnull=False)
                    | ~models.Q(value_text="")
                    | models.Q(value_number__isnull=False)
                ),
                name="assertion_value_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_year__isnull=True)
                    | models.Q(time_end_year__isnull=True)
                    | models.Q(time_start_year__lte=models.F("time_end_year"))
                ),
                name="assertion_time_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_month__isnull=True)
                    | models.Q(time_start_month__gte=1, time_start_month__lte=12)
                ),
                name="assertion_start_month_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_end_month__isnull=True)
                    | models.Q(time_end_month__gte=1, time_end_month__lte=12)
                ),
                name="assertion_end_month_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_day__isnull=True)
                    | models.Q(time_start_day__gte=1, time_start_day__lte=31)
                ),
                name="assertion_start_day_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_end_day__isnull=True)
                    | models.Q(time_end_day__gte=1, time_end_day__lte=31)
                ),
                name="assertion_end_day_range",
            ),
            models.CheckConstraint(condition=~models.Q(confidence_reason=""), name="assertion_confidence_reason_required"),
        ]

    @property
    def display_value(self):
        if self.value_text:
            return self.value_text
        if self.object_entity_id:
            return self.object_entity.canonical_name
        if self.value_number is not None:
            return str(self.value_number)
        return ""

    def __str__(self):
        return f"{self.subject} – {self.predicate}"

    def clean(self):
        errors = {}
        if self.object_entity_id is None and not self.value_text and self.value_number is None:
            errors["value_text"] = "Eine Aussage benötigt ein Objekt oder einen Wert."
        if self.time_start_day is not None and self.time_start_month is None:
            errors["time_start_day"] = "Ein genauer Tag benötigt einen Monat."
        if self.time_end_day is not None and self.time_end_month is None:
            errors["time_end_day"] = "Ein genauer Tag benötigt einen Monat."
        if (self.time_start_month is not None or self.time_start_day is not None) and self.time_start_year is None:
            errors["time_start_year"] = "Monat und Tag benötigen ein Jahr."
        if (self.time_end_month is not None or self.time_end_day is not None) and self.time_end_year is None:
            errors["time_end_year"] = "Monat und Tag benötigen ein Jahr."
        if self.temporal_scope == self.TemporalScope.BOUNDED and (
            self.time_start_year is None or self.time_end_year is None
        ):
            errors["temporal_scope"] = "Ein begrenzter Zeitraum benötigt Anfangs- und Endjahr."
        if self.time_start_year is not None and self.time_end_year is not None:
            start = (self.time_start_year, self.time_start_month or 1, self.time_start_day or 1)
            end = (self.time_end_year, self.time_end_month or 12, self.time_end_day or 31)
            if start > end:
                errors["time_end_year"] = "Das Ende darf nicht vor dem Anfang liegen."
        if self.spatial_scope == self.SpatialScope.POINT and self.location is None:
            errors["spatial_scope"] = "Ein punktgenauer Raumbezug benötigt Koordinaten."
        if not self.confidence_reason.strip():
            errors["confidence_reason"] = "Der Vertrauenswert benötigt eine kurze Begründung."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.temporal_scope == self.TemporalScope.UNKNOWN:
            if self.time_start_year is not None and self.time_end_year is not None:
                self.temporal_scope = self.TemporalScope.BOUNDED
            elif self.time_start_year is not None:
                self.temporal_scope = self.TemporalScope.OPEN_END
            elif self.time_end_year is not None:
                self.temporal_scope = self.TemporalScope.OPEN_START
        if self.spatial_scope == self.SpatialScope.UNKNOWN and self.location is not None:
            self.spatial_scope = self.SpatialScope.POINT
        if self.knowledge_type == self.KnowledgeType.AUTOMATIC_EXTRACTION and self.extraction_method.startswith(
            ("manual", "curated")
        ):
            self.knowledge_type = self.KnowledgeType.DOCUMENTED
        if self.confidence_reason == default_confidence_reason():
            if self.extraction_method.startswith("manual"):
                self.confidence_reason = "Manuell erfasste Aussage; Vertrauenswert aus der zugeordneten Evidenz."
            elif self.extraction_method.startswith("curated"):
                self.confidence_reason = "Redaktionell kuratierte Aussage; Vertrauenswert aus der zugeordneten Evidenz."
        self.clean()
        super().save(*args, **kwargs)

    @property
    def temporal_extent(self):
        return {
            "scope": self.temporal_scope,
            "start": {
                "year": self.time_start_year,
                "month": self.time_start_month,
                "day": self.time_start_day,
            },
            "end": {
                "year": self.time_end_year,
                "month": self.time_end_month,
                "day": self.time_end_day,
            },
            "precision": self.time_precision,
            "uncertainty_years": self.temporal_uncertainty_years,
            "calendar": self.calendar_model,
            "note": self.temporal_note,
        }

    def integrity_issues(self):
        issues = []
        if self.object_entity_id is None and not self.value_text and self.value_number is None:
            issues.append("missing_value")
        if self.temporal_scope == self.TemporalScope.BOUNDED and (
            self.time_start_year is None or self.time_end_year is None
        ):
            issues.append("missing_bounded_time")
        if self.spatial_scope == self.SpatialScope.POINT and self.location is None:
            issues.append("missing_point")
        if not self.confidence_reason.strip():
            issues.append("missing_confidence_reason")
        if self.pk and not self.evidence.exists():
            issues.append("missing_evidence")
        return issues


class Evidence(models.Model):
    class Relation(models.TextChoices):
        SUPPORTS = "supports", "stützt"
        REFUTES = "refutes", "widerspricht"
        MENTIONS = "mentions", "erwähnt"

    assertion = models.ForeignKey(Assertion, related_name="evidence", on_delete=models.CASCADE)
    source = models.ForeignKey(Source, related_name="evidence", on_delete=models.CASCADE)
    relation = models.CharField(max_length=16, choices=Relation.choices, default=Relation.SUPPORTS)
    locator = models.CharField(max_length=500, default="Nicht näher bezeichnete Fundstelle")
    excerpt = models.TextField(blank=True, help_text="Nur kurzer Belegauszug oder Paraphrase")
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=0.5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assertion", "source", "relation"], name="unique_assertion_evidence"),
            models.CheckConstraint(condition=~models.Q(locator=""), name="evidence_locator_required"),
        ]


class AssertionRelation(models.Model):
    """Explizite Beziehung zwischen Aussagen; Gleichzeitigkeit ist nie automatisch Kausalität."""

    class Type(models.TextChoices):
        CAUSES = "causes", "Verursacht"
        CONTRIBUTES_TO = "contributes_to", "Trägt bei zu"
        INFLUENCES = "influences", "Beeinflusst"
        PART_OF = "part_of", "Ist Teil von"
        REACTION_TO = "reaction_to", "Ist Reaktion auf"
        SIMILAR_TO = "similar_to", "Ähnelt"
        CONTEMPORARY_WITH = "contemporary_with", "Ist gleichzeitig mit"
        SUPPORTS = "supports", "Stützt"
        CONTRADICTS = "contradicts", "Widerspricht"
        SPATIAL_OVERLAP = "spatial_overlap", "Räumliche Überschneidung"

    class EvidenceLevel(models.TextChoices):
        DOCUMENTED = "documented", "Belegter Zusammenhang"
        SCHOLARLY_PLAUSIBLE = "scholarly_plausible", "Wissenschaftlich plausible Einordnung"
        ALGORITHMIC_SIMILARITY = "algorithmic_similarity", "Automatisch erkannte Ähnlichkeit"
        COINCIDENCE = "coincidence", "Bloße Gleichzeitigkeit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_assertion = models.ForeignKey(Assertion, related_name="outgoing_relations", on_delete=models.CASCADE)
    target_assertion = models.ForeignKey(Assertion, related_name="incoming_relations", on_delete=models.CASCADE)
    relation_type = models.CharField(max_length=32, choices=Type.choices)
    evidence_level = models.CharField(max_length=32, choices=EvidenceLevel.choices)
    summary = models.TextField()
    mechanism = models.TextField(blank=True)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confidence_reason = models.TextField()
    temporal_overlap_years = models.BigIntegerField(null=True, blank=True)
    spatial_distance_meters = models.PositiveBigIntegerField(null=True, blank=True)
    extraction_method = models.CharField(max_length=120, default="manual")
    algorithm_name = models.CharField(max_length=160, blank=True)
    algorithm_version = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, choices=Assertion.Status.choices, default=Assertion.Status.CANDIDATE)
    evidence = models.ManyToManyField(Evidence, related_name="assertion_relations", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["relation_type", "evidence_level"]),
            models.Index(fields=["status", "confidence"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_assertion", "target_assertion", "relation_type", "evidence_level"],
                name="unique_assertion_relation",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_assertion=models.F("target_assertion")),
                name="assertion_relation_distinct_assertions",
            ),
            models.CheckConstraint(condition=~models.Q(summary=""), name="assertion_relation_summary_required"),
            models.CheckConstraint(
                condition=~models.Q(confidence_reason=""),
                name="assertion_relation_confidence_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(evidence_level="coincidence")
                    | models.Q(relation_type="contemporary_with")
                ),
                name="coincidence_is_only_contemporary",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(evidence_level="algorithmic_similarity")
                    | models.Q(relation_type="similar_to")
                ),
                name="algorithmic_similarity_relation_type",
            ),
        ]

    def clean(self):
        errors = {}
        if self.source_assertion_id and self.source_assertion_id == self.target_assertion_id:
            errors["target_assertion"] = "Eine Aussage kann nicht mit sich selbst verknüpft werden."
        if self.evidence_level == self.EvidenceLevel.COINCIDENCE and self.relation_type != self.Type.CONTEMPORARY_WITH:
            errors["evidence_level"] = "Bloße Gleichzeitigkeit darf nicht als kausale Beziehung gespeichert werden."
        if self.evidence_level == self.EvidenceLevel.ALGORITHMIC_SIMILARITY:
            if self.relation_type != self.Type.SIMILAR_TO:
                errors["relation_type"] = "Automatisch erkannte Ähnlichkeit benötigt den Beziehungstyp ‚ähnelt‘."
            if not self.algorithm_name or not self.algorithm_version:
                errors["algorithm_name"] = "Algorithmus und Version müssen nachvollziehbar angegeben werden."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.source_assertion} → {self.get_relation_type_display()} → {self.target_assertion}"


class HistoricalProcess(models.Model):
    """Ein längerfristiger Prozess, der durch einzelne Aussagen belegt und räumlich-zeitlich begrenzt wird."""

    class Type(models.TextChoices):
        INTELLECTUAL = "intellectual", "Ideen- und Wissensgeschichte"
        POLITICAL = "political", "Politischer Prozess"
        SOCIAL = "social", "Gesellschaftlicher Prozess"
        ECONOMIC = "economic", "Wirtschaftlicher Prozess"
        RELIGIOUS = "religious", "Religiöser Prozess"
        CULTURAL = "cultural", "Kultureller Prozess"
        ENVIRONMENTAL = "environmental", "Umwelt- und Klimaprozess"
        TECHNOLOGICAL = "technological", "Technischer Prozess"
        DEMOGRAPHIC = "demographic", "Demografischer Prozess"
        OTHER = "other", "Sonstiger Prozess"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.OneToOneField(Entity, related_name="historical_process", on_delete=models.CASCADE)
    process_type = models.CharField(max_length=24, choices=Type.choices)
    summary = models.TextField()
    time_start_year = models.BigIntegerField(null=True, blank=True)
    time_end_year = models.BigIntegerField(null=True, blank=True)
    time_precision = models.CharField(
        max_length=16,
        choices=Assertion.Precision.choices,
        default=Assertion.Precision.UNKNOWN,
    )
    temporal_uncertainty_years = models.PositiveBigIntegerField(default=0)
    temporal_scope = models.CharField(
        max_length=16,
        choices=Assertion.TemporalScope.choices,
        default=Assertion.TemporalScope.UNKNOWN,
    )
    spatial_extent = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_scope = models.CharField(
        max_length=16,
        choices=Assertion.SpatialScope.choices,
        default=Assertion.SpatialScope.UNKNOWN,
    )
    spatial_precision_meters = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Assertion.Status.choices,
        default=Assertion.Status.CANDIDATE,
    )
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confidence_reason = models.TextField(default=default_confidence_reason)
    defining_assertions = models.ManyToManyField(
        Assertion,
        related_name="defined_processes",
        blank=True,
        help_text="Aussagen, die Existenz, Zeitraum oder Raumbezug des Prozesses stützen.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["process_type", "status"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
            models.Index(fields=["spatial_scope", "confidence"]),
        ]
        constraints = [
            models.CheckConstraint(condition=~models.Q(summary=""), name="historical_process_summary_required"),
            models.CheckConstraint(
                condition=~models.Q(confidence_reason=""),
                name="historical_process_confidence_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_year__isnull=True)
                    | models.Q(time_end_year__isnull=True)
                    | models.Q(time_start_year__lte=models.F("time_end_year"))
                ),
                name="historical_process_time_order",
            ),
        ]

    def clean(self):
        errors = {}
        if self.entity_id and self.entity.kind != Entity.Kind.PROCESS:
            errors["entity"] = "Die zugeordnete Entität muss als historischer Prozess klassifiziert sein."
        if self.temporal_scope == Assertion.TemporalScope.BOUNDED and (
            self.time_start_year is None or self.time_end_year is None
        ):
            errors["temporal_scope"] = "Ein begrenzter Prozess benötigt Anfangs- und Endjahr."
        if (
            self.time_start_year is not None
            and self.time_end_year is not None
            and self.time_start_year > self.time_end_year
        ):
            errors["time_end_year"] = "Das Ende darf nicht vor dem Anfang liegen."
        if self.spatial_scope == Assertion.SpatialScope.POINT and self.spatial_extent is None:
            errors["spatial_scope"] = "Ein punktgenauer Prozess benötigt eine Geometrie."
        if not self.summary.strip():
            errors["summary"] = "Ein Prozess benötigt eine kurze Beschreibung."
        if not self.confidence_reason.strip():
            errors["confidence_reason"] = "Der Vertrauenswert benötigt eine kurze Begründung."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.temporal_scope == Assertion.TemporalScope.UNKNOWN:
            if self.time_start_year is not None and self.time_end_year is not None:
                self.temporal_scope = Assertion.TemporalScope.BOUNDED
            elif self.time_start_year is not None:
                self.temporal_scope = Assertion.TemporalScope.OPEN_END
            elif self.time_end_year is not None:
                self.temporal_scope = Assertion.TemporalScope.OPEN_START
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def temporal_extent(self):
        return {
            "scope": self.temporal_scope,
            "start_year": self.time_start_year,
            "end_year": self.time_end_year,
            "precision": self.time_precision,
            "uncertainty_years": self.temporal_uncertainty_years,
        }

    def integrity_issues(self):
        issues = []
        if self.pk and not self.defining_assertions.exists():
            issues.append("missing_defining_assertion")
        if self.pk and not self.defining_assertions.filter(evidence__isnull=False).exists():
            issues.append("missing_source_evidence")
        if not self.confidence_reason.strip():
            issues.append("missing_confidence_reason")
        return issues

    def __str__(self):
        return self.entity.canonical_name


class ProcessAssertionRelation(models.Model):
    """Ordnet eine einzelne Aussage einem Prozess zu, ohne aus Gleichzeitigkeit Kausalität abzuleiten."""

    class Type(models.TextChoices):
        MANIFESTS_IN = "manifests_in", "Manifestiert sich in"
        MATERIAL_TRACE = "material_trace", "Hinterlässt materielle Spur"
        INSTITUTIONALIZED_BY = "institutionalized_by", "Wird institutionalisiert durch"
        LEGITIMIZED_BY = "legitimized_by", "Wird legitimiert durch"
        SPREADS_THROUGH = "spreads_through", "Verbreitet sich durch"
        INFLUENCES = "influences", "Beeinflusst"
        CONTRIBUTES_TO = "contributes_to", "Trägt bei zu"
        REACTION_TO = "reaction_to", "Ist Reaktion auf"
        OPPOSES = "opposes", "Steht im Gegensatz zu"
        PART_OF = "part_of", "Ist Teil von"
        SIMILAR_TO = "similar_to", "Ähnelt"
        CONTEMPORARY_WITH = "contemporary_with", "Ist gleichzeitig mit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    process = models.ForeignKey(HistoricalProcess, related_name="assertion_relations", on_delete=models.CASCADE)
    assertion = models.ForeignKey(Assertion, related_name="process_relations", on_delete=models.CASCADE)
    relation_type = models.CharField(max_length=32, choices=Type.choices)
    evidence_level = models.CharField(max_length=32, choices=AssertionRelation.EvidenceLevel.choices)
    summary = models.TextField()
    mechanism = models.TextField(blank=True)
    time_start_year = models.BigIntegerField(null=True, blank=True)
    time_end_year = models.BigIntegerField(null=True, blank=True)
    temporal_uncertainty_years = models.PositiveBigIntegerField(default=0)
    spatial_extent = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_precision_meters = models.PositiveBigIntegerField(null=True, blank=True)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confidence_reason = models.TextField()
    extraction_method = models.CharField(max_length=120, default="manual")
    algorithm_name = models.CharField(max_length=160, blank=True)
    algorithm_version = models.CharField(max_length=80, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Assertion.Status.choices,
        default=Assertion.Status.CANDIDATE,
    )
    evidence = models.ManyToManyField(Evidence, related_name="process_assertion_relations", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["relation_type", "evidence_level"]),
            models.Index(fields=["status", "confidence"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["process", "assertion", "relation_type", "evidence_level"],
                name="unique_process_assertion_relation",
            ),
            models.CheckConstraint(condition=~models.Q(summary=""), name="process_relation_summary_required"),
            models.CheckConstraint(
                condition=~models.Q(confidence_reason=""),
                name="process_relation_confidence_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_year__isnull=True)
                    | models.Q(time_end_year__isnull=True)
                    | models.Q(time_start_year__lte=models.F("time_end_year"))
                ),
                name="process_relation_time_order",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(evidence_level="coincidence")
                    | models.Q(relation_type="contemporary_with")
                ),
                name="process_coincidence_is_only_contemporary",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(evidence_level="algorithmic_similarity")
                    | models.Q(relation_type="similar_to")
                ),
                name="process_algorithmic_similarity_type",
            ),
        ]

    def clean(self):
        errors = {}
        if (
            self.evidence_level == AssertionRelation.EvidenceLevel.COINCIDENCE
            and self.relation_type != self.Type.CONTEMPORARY_WITH
        ):
            errors["evidence_level"] = "Bloße Gleichzeitigkeit darf nicht als Wirkung des Prozesses gespeichert werden."
        if self.evidence_level == AssertionRelation.EvidenceLevel.ALGORITHMIC_SIMILARITY:
            if self.relation_type != self.Type.SIMILAR_TO:
                errors["relation_type"] = "Automatisch erkannte Ähnlichkeit benötigt den Beziehungstyp ‚ähnelt‘."
            if not self.algorithm_name or not self.algorithm_version:
                errors["algorithm_name"] = "Algorithmus und Version müssen nachvollziehbar angegeben werden."
        if (
            self.time_start_year is not None
            and self.time_end_year is not None
            and self.time_start_year > self.time_end_year
        ):
            errors["time_end_year"] = "Das Ende darf nicht vor dem Anfang liegen."
        if not self.summary.strip():
            errors["summary"] = "Die Beziehung benötigt eine kurze Beschreibung."
        if not self.confidence_reason.strip():
            errors["confidence_reason"] = "Der Vertrauenswert benötigt eine kurze Begründung."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def integrity_issues(self):
        issues = []
        if (
            self.evidence_level
            in {
                AssertionRelation.EvidenceLevel.DOCUMENTED,
                AssertionRelation.EvidenceLevel.SCHOLARLY_PLAUSIBLE,
            }
            and self.pk
            and not self.evidence.exists()
        ):
            issues.append("missing_relation_evidence")
        return issues

    def __str__(self):
        return f"{self.process} → {self.get_relation_type_display()} → {self.assertion}"


class WikipediaPortal(models.Model):
    """Kuratierter Wikipedia-Einstieg; das Portal selbst ist keine Tatsachenevidenz."""

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        RUNNING = "running", "Wird ausgewertet"
        COMPLETE = "complete", "Abgeschlossen"
        PARTIAL = "partial", "Teilweise abgeschlossen"
        FAILED = "failed", "Fehlgeschlagen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    language = models.CharField(max_length=24)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1200)
    page_id = models.BigIntegerField(null=True, blank=True)
    revision_id = models.BigIntegerField(null=True, blank=True)
    subject_entity = models.ForeignKey(
        Entity,
        related_name="wikipedia_portals",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    scan_status = models.CharField(max_length=16, choices=ScanStatus.choices, default=ScanStatus.PENDING)
    article_count = models.PositiveIntegerField(default=0)
    assertion_count = models.PositiveIntegerField(default=0)
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["language", "title"], name="unique_wikipedia_portal")
        ]
        indexes = [
            models.Index(fields=["language", "scan_status"]),
            models.Index(fields=["last_scanned_at"]),
        ]

    def __str__(self):
        return f"{self.language}: {self.title}"


class PortalArticle(models.Model):
    """Ein im Portal gefundener Artikel samt daraus gewonnenen Aussagen."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal = models.ForeignKey(WikipediaPortal, related_name="articles", on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1200)
    page_id = models.BigIntegerField(null=True, blank=True)
    revision_id = models.BigIntegerField(null=True, blank=True)
    source = models.ForeignKey(
        Source,
        related_name="portal_articles",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    assertions = models.ManyToManyField(Assertion, related_name="portal_discoveries", blank=True)
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["portal", "title"], name="unique_portal_article")
        ]
        indexes = [models.Index(fields=["portal", "active", "position"])]

    def __str__(self):
        return f"{self.portal} → {self.title}"


class PortalScanRun(models.Model):
    """Auditierbarer einzelner Scan, einschließlich Teilständen und Fehlern."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal = models.ForeignKey(WikipediaPortal, related_name="scan_runs", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=16,
        choices=WikipediaPortal.ScanStatus.choices,
        default=WikipediaPortal.ScanStatus.RUNNING,
    )
    portal_revision_id = models.BigIntegerField(null=True, blank=True)
    discovered_articles = models.PositiveIntegerField(default=0)
    processed_articles = models.PositiveIntegerField(default=0)
    discovered_assertions = models.PositiveIntegerField(default=0)
    continuation = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["portal", "started_at"])]

    def __str__(self):
        return f"{self.portal} · {self.status}"


class EnvironmentalDataset(models.Model):
    """Katalogeintrag für externe Umweltbestände; große Raster bleiben außerhalb von PostgreSQL."""

    class DataKind(models.TextChoices):
        VECTOR = "vector", "Vektordaten"
        RASTER = "raster", "Rasterdaten"
        STATION = "station", "Stationsdaten"
        RECONSTRUCTION = "reconstruction", "Rekonstruktion"
        DOCUMENT = "document", "Dokumentarische Beobachtung"

    class StorageKind(models.TextChoices):
        EXTERNAL = "external", "Externe Quelle"
        OBJECT = "object", "Objektspeicher"
        DATABASE = "database", "Datenbankausschnitt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=500)
    provider = models.CharField(max_length=200)
    source = models.ForeignKey(Source, related_name="environmental_datasets", on_delete=models.PROTECT)
    data_kind = models.CharField(max_length=24, choices=DataKind.choices)
    storage_kind = models.CharField(max_length=24, choices=StorageKind.choices, default=StorageKind.EXTERNAL)
    asset_uri = models.CharField(max_length=1600, blank=True)
    file_format = models.CharField(max_length=80, blank=True)
    variable_name = models.CharField(max_length=160, blank=True)
    unit = models.CharField(max_length=80, blank=True)
    spatial_coverage = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_resolution_meters = models.PositiveBigIntegerField(null=True, blank=True)
    spatial_resolution_text = models.CharField(max_length=200, blank=True)
    time_start_year = models.BigIntegerField(null=True, blank=True)
    time_end_year = models.BigIntegerField(null=True, blank=True)
    reference_period_start_year = models.BigIntegerField(null=True, blank=True)
    reference_period_end_year = models.BigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "data_kind"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(time_start_year__isnull=True)
                    | models.Q(time_end_year__isnull=True)
                    | models.Q(time_start_year__lte=models.F("time_end_year"))
                ),
                name="environmental_dataset_time_order",
            )
        ]

    def __str__(self):
        return self.title


class EnvironmentalEvent(models.Model):
    class Type(models.TextChoices):
        VOLCANO = "volcano", "Vulkanausbruch"
        EARTHQUAKE = "earthquake", "Erdbeben"
        TSUNAMI = "tsunami", "Tsunami"
        STORM_SURGE = "storm_surge", "Sturmflut"
        DROUGHT = "drought", "Dürre"
        HEATWAVE = "heatwave", "Hitzewelle"
        FROST = "frost", "Frost / Kälteperiode"
        FLOOD = "flood", "Hochwasser"
        RIVER_COURSE_CHANGE = "river_course_change", "Flusslaufverlagerung"
        OTHER = "other", "Anderes Naturereignis"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(
        EnvironmentalDataset,
        related_name="events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    external_id = models.CharField(max_length=300, blank=True)
    event_type = models.CharField(max_length=24, choices=Type.choices)
    name = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    geometry = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_resolution_meters = models.PositiveBigIntegerField(null=True, blank=True)
    time_start_year = models.BigIntegerField()
    time_end_year = models.BigIntegerField()
    time_precision = models.CharField(max_length=16, choices=Assertion.Precision.choices, default=Assertion.Precision.YEAR)
    temporal_uncertainty_years = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Assertion.Status.choices, default=Assertion.Status.CANDIDATE)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    evidence = models.ManyToManyField(Evidence, related_name="environmental_events", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "status"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(time_start_year__lte=models.F("time_end_year")),
                name="environmental_event_time_order",
            ),
            models.UniqueConstraint(
                fields=["dataset", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_environmental_event_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.time_start_year})"


class EnvironmentalObservation(models.Model):
    class Method(models.TextChoices):
        MEASUREMENT = "measurement", "Messung"
        RECONSTRUCTION = "reconstruction", "Rekonstruktion"
        DOCUMENTARY = "documentary", "Dokumentarische Beobachtung"

    class SpatialScope(models.TextChoices):
        LOCAL = "local", "Lokal"
        REGIONAL = "regional", "Regional"
        HEMISPHERIC = "hemispheric", "Hemisphärisch"
        GLOBAL = "global", "Global"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(EnvironmentalDataset, related_name="observations", on_delete=models.PROTECT)
    event = models.ForeignKey(
        EnvironmentalEvent,
        related_name="observations",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    external_id = models.CharField(max_length=300, blank=True)
    method = models.CharField(max_length=24, choices=Method.choices)
    variable = models.CharField(max_length=160)
    value = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    value_min = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    value_max = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    value_text = models.TextField(blank=True)
    unit = models.CharField(max_length=80, blank=True)
    geometry = models.GeometryField(srid=4326, geography=True, null=True, blank=True)
    spatial_scope = models.CharField(max_length=24, choices=SpatialScope.choices, default=SpatialScope.LOCAL)
    spatial_resolution_meters = models.PositiveBigIntegerField(null=True, blank=True)
    time_start_year = models.BigIntegerField()
    time_end_year = models.BigIntegerField()
    time_precision = models.CharField(max_length=16, choices=Assertion.Precision.choices, default=Assertion.Precision.YEAR)
    temporal_uncertainty_years = models.PositiveBigIntegerField(default=0)
    reference_period_start_year = models.BigIntegerField(null=True, blank=True)
    reference_period_end_year = models.BigIntegerField(null=True, blank=True)
    aggregation = models.CharField(max_length=120, blank=True)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    status = models.CharField(max_length=16, choices=Assertion.Status.choices, default=Assertion.Status.CANDIDATE)
    asset_uri = models.CharField(max_length=1600, blank=True)
    asset_window = models.JSONField(default=dict, blank=True)
    evidence = models.ManyToManyField(Evidence, related_name="environmental_observations", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["variable", "method"]),
            models.Index(fields=["time_start_year", "time_end_year"]),
            models.Index(fields=["spatial_scope"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(time_start_year__lte=models.F("time_end_year")),
                name="environmental_observation_time_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(reference_period_start_year__isnull=True)
                    | models.Q(reference_period_end_year__isnull=True)
                    | models.Q(reference_period_start_year__lte=models.F("reference_period_end_year"))
                ),
                name="environmental_observation_reference_order",
            ),
            models.UniqueConstraint(
                fields=["dataset", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_environmental_observation_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.variable}: {self.value if self.value is not None else self.value_text}"


class EnvironmentalRelation(models.Model):
    class Type(models.TextChoices):
        DOCUMENTED = "documented", "Dokumentierte Auswirkung"
        POSSIBLE = "possible", "Möglicher Beitrag"
        COINCIDENCE = "coincidence", "Zeitliche Koinzidenz"
        DISPUTED = "disputed", "Umstrittener Zusammenhang"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environmental_event = models.ForeignKey(
        EnvironmentalEvent,
        related_name="historical_relations",
        on_delete=models.CASCADE,
    )
    historical_assertion = models.ForeignKey(
        Assertion,
        related_name="environmental_relations",
        on_delete=models.CASCADE,
    )
    relation_type = models.CharField(max_length=24, choices=Type.choices, default=Type.POSSIBLE)
    summary = models.TextField()
    mechanism = models.TextField(blank=True)
    temporal_lag_years = models.IntegerField(default=0)
    temporal_confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    spatial_confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    status = models.CharField(max_length=16, choices=Assertion.Status.choices, default=Assertion.Status.CANDIDATE)
    uncertainty_note = models.TextField(blank=True)
    evidence = models.ManyToManyField(Evidence, related_name="environmental_relations", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["relation_type", "status"]), models.Index(fields=["confidence"])]
        constraints = [
            models.UniqueConstraint(
                fields=["environmental_event", "historical_assertion", "relation_type"],
                name="unique_environmental_historical_relation",
            )
        ]

    def __str__(self):
        return self.summary[:120]


class ResearchRequest(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Vorgemerkt"
        RUNNING = "running", "Recherche läuft"
        COMPLETE = "complete", "Abgeschlossen"
        PARTIAL = "partial", "Teilweise abgeschlossen"
        FAILED = "failed", "Fehlgeschlagen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    query = models.CharField(max_length=500, blank=True)
    center = models.PointField(srid=4326, geography=True)
    radius_km = models.PositiveIntegerField(default=25)
    time_start_year = models.BigIntegerField()
    time_end_year = models.BigIntegerField()
    topics = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=default_research_languages)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    trigger_count = models.PositiveIntegerField(default=1)
    discovered_assertions = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_requested_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "last_requested_at"])]


class ExplorationContext(models.Model):
    """Persistierter Raum-Zeit-Zustand für alle Eingabekanäle eines Clients."""

    class AnchorMode(models.TextChoices):
        SPACE = "space", "Ort als Ausgangspunkt"
        EVENT = "event", "Ereignis als Ausgangspunkt"
        TIME = "time", "Zeit als Ausgangspunkt"
        ENVIRONMENT = "environment", "Naturereignis-Kategorie als Ausgangspunkt"

    class QueryMode(models.TextChoices):
        AUTO = "auto", "Automatisch erkennen"
        PLACE = "place", "Ort"
        EVENT = "event", "Ereignis"
        TOPIC = "topic", "Thema"
        ENVIRONMENT = "environment", "Naturereignis-Kategorie"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    place_name = models.CharField(max_length=300, default="Krempe")
    center = models.PointField(srid=4326, geography=True, default=default_exploration_center)
    map_zoom = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=11,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    time_focus_year = models.BigIntegerField(default=1814)
    time_window_years = models.PositiveBigIntegerField(default=0)
    time_unbounded = models.BooleanField(default=False)
    radius_km = models.PositiveIntegerField(
        default=25,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
    )
    space_unbounded = models.BooleanField(default=False)
    query = models.CharField(max_length=500, blank=True)
    query_mode = models.CharField(max_length=16, choices=QueryMode.choices, default=QueryMode.AUTO)
    anchor_mode = models.CharField(max_length=16, choices=AnchorMode.choices, default=AnchorMode.SPACE)
    focus_entity = models.ForeignKey(
        Entity,
        related_name="focused_exploration_contexts",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    event_start_year = models.BigIntegerField(null=True, blank=True)
    event_end_year = models.BigIntegerField(null=True, blank=True)
    environmental_event_types = models.JSONField(default=list, blank=True)
    environmental_place_name = models.CharField(max_length=300, blank=True)
    topics = models.JSONField(default=list, blank=True)
    perspectives = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=default_research_languages)
    include_candidates = models.BooleanField(default=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["updated_at"]),
            models.Index(fields=["time_focus_year"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(radius_km__gte=1, radius_km__lte=1000), name="context_radius_range"),
            models.CheckConstraint(condition=models.Q(map_zoom__gte=1, map_zoom__lte=20), name="context_zoom_range"),
            models.CheckConstraint(condition=models.Q(time_window_years__lte=1_000_000_000), name="context_time_window_range"),
        ]

    @property
    def time_start_year(self):
        return self.time_focus_year - self.time_window_years

    @property
    def time_end_year(self):
        return self.time_focus_year + self.time_window_years

    def __str__(self):
        return f"{self.place_name} · {self.time_focus_year}"


class Coverage(models.Model):
    cell_key = models.CharField(max_length=120)
    time_start_year = models.BigIntegerField()
    time_end_year = models.BigIntegerField()
    topic = models.CharField(max_length=120, default="allgemein")
    language = models.CharField(max_length=24, default="de")
    score = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    source_count = models.PositiveIntegerField(default=0)
    assertion_count = models.PositiveIntegerField(default=0)
    last_researched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cell_key", "time_start_year", "time_end_year", "topic", "language"],
                name="unique_coverage_slice",
            )
        ]
