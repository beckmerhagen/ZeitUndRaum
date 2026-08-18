from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from knowledge.models import (
    Assertion,
    AssertionRelation,
    Entity,
    ExternalIdentifier,
    HistoricalProcess,
    ProcessAssertionRelation,
)


EXTRACTION_METHOD = "curated-dossier-v1"


def translated(values, language="de"):
    return values.get(language) or values.get("en") or next(iter(values.values()))


def assertions_for_terms(terms, start_year, end_year, limit=30):
    text_filter = Q()
    for term in terms:
        text_filter |= Q(subject__canonical_name__icontains=term) | Q(value_text__icontains=term)
    return list(
        Assertion.objects.exclude(status=Assertion.Status.REJECTED)
        .exclude(time_start_year__isnull=True, time_end_year__isnull=True)
        .filter(text_filter, evidence__relation="supports")
        .filter(Q(time_start_year__isnull=True) | Q(time_start_year__lte=end_year))
        .filter(Q(time_end_year__isnull=True) | Q(time_end_year__gte=start_year))
        .select_related("subject")
        .prefetch_related("evidence__source")
        .distinct()
        .order_by("-confidence", "time_start_year")[:limit]
    )


class Command(BaseCommand):
    help = "Legt kuratierte, evidenzbewusste Startdossiers idempotent an."

    @transaction.atomic
    def handle(self, *args, **options):
        configs = [
            {
                "slug": "malta-political-turning-points",
                "labels": {
                    "de": "Malta: Belagerung, Militärstützpunkt und europäische Integration",
                    "en": "Malta: siege, military base and European integration",
                    "fr": "Malte : siège, base militaire et intégration européenne",
                },
                "summaries": {
                    "de": "Ein kuratierter Pfad durch drei amtlich belegte politische Wendepunkte Maltas. Die zeitliche Folge allein behauptet keine durchgehende Ursache-Wirkungs-Kette.",
                    "en": "A curated path through three officially documented political turning points in Malta. Their sequence alone does not establish a continuous causal chain.",
                    "fr": "Un parcours organisé autour de trois tournants politiques de Malte documentés par des sources officielles. Leur succession ne prouve pas une chaîne causale continue.",
                },
                "questions": {
                    "de": "Wie veränderte sich Maltas strategische und politische Einbindung?",
                    "en": "How did Malta's strategic and political alignment change?",
                    "fr": "Comment l'ancrage stratégique et politique de Malte a-t-il changé ?",
                },
                "process_type": HistoricalProcess.Type.POLITICAL,
                "start": 1565,
                "end": 2004,
                "scope": Assertion.SpatialScope.REGION,
                "point": Point(14.4477, 35.8880, srid=4326),
                "precision": 30000,
                "status": Assertion.Status.VERIFIED,
                "confidence": Decimal("0.960"),
                "reason": "Drei einzeln belegte Meilensteine aus Quellen der Regierung Maltas und der Europäischen Kommission; die Dossier-Klammer ist redaktionell ausgewiesen.",
                "assertions": list(
                    Assertion.objects.filter(extraction_method="curated-official-source-v1")
                    .filter(time_start_year__in=[1565, 1979, 2004])
                    .prefetch_related("evidence__source")
                    .order_by("time_start_year")
                ),
            },
            {
                "slug": "krempe-built-memory",
                "labels": {
                    "de": "Krempe: Bauwerke, Krieg und lokale Erinnerung",
                    "en": "Krempe: buildings, war and local memory",
                    "fr": "Krempe : bâtiments, guerre et mémoire locale",
                },
                "summaries": {
                    "de": "Belegte Ortsmarken verbinden Kirchen- und Rathausgeschichte mit Krempes Rolle als umkämpfter Festung. Das Dossier trennt Baugeschichte, Naturereignis und Kriegseinwirkung.",
                    "en": "Documented local milestones connect church and town-hall history with Krempe's role as a contested fortress. The dossier keeps building history, natural events and warfare distinct.",
                    "fr": "Des jalons locaux documentés relient l'histoire de l'église et de l'hôtel de ville au rôle de Krempe comme forteresse disputée, tout en distinguant construction, événements naturels et guerre.",
                },
                "questions": {
                    "de": "Welche großen Prozesse werden an einzelnen Bauwerken in Krempe sichtbar?",
                    "en": "Which larger processes become visible in Krempe's individual buildings?",
                    "fr": "Quels grands processus deviennent visibles dans les bâtiments de Krempe ?",
                },
                "process_type": HistoricalProcess.Type.CULTURAL,
                "start": 1239,
                "end": 1832,
                "scope": Assertion.SpatialScope.REGION,
                "point": Point(9.489, 53.836, srid=4326),
                "precision": 3000,
                "status": Assertion.Status.VERIFIED,
                "confidence": Decimal("0.880"),
                "reason": "Sieben datierte Aussagen mit lokaler, institutioneller oder enzyklopädischer Evidenz; weitergehende Zusammenhänge werden nicht automatisch behauptet.",
                "assertions": list(
                    Assertion.objects.filter(extraction_method="curated-demo-v1")
                    .prefetch_related("evidence__source")
                    .order_by("time_start_year")
                ),
            },
            {
                "slug": "tambora-1815-1816",
                "labels": {
                    "de": "Tambora, Atmosphäre und das Jahr ohne Sommer 1815–1816",
                    "en": "Tambora, the atmosphere and the Year Without a Summer, 1815–1816",
                    "fr": "Tambora, l'atmosphère et l'année sans été, 1815–1816",
                },
                "summaries": {
                    "de": "Ein Pilotdossier zum Ausbruch des Tambora und zeitgleichen atmosphärischen Befunden. Konkrete historische Folgen werden nur dort als Zusammenhang gezeigt, wo eine eigene Quelle sie belegt.",
                    "en": "A pilot dossier on the Tambora eruption and contemporary atmospheric findings. Specific historical consequences are shown as connections only where a dedicated source supports them.",
                    "fr": "Un dossier pilote sur l'éruption du Tambora et les observations atmosphériques contemporaines. Les conséquences historiques ne sont reliées que lorsqu'une source propre les étaye.",
                },
                "questions": {
                    "de": "Welche regionalen Folgen der globalen atmosphärischen Störung sind tatsächlich belegt?",
                    "en": "Which regional consequences of the global atmospheric disturbance are actually documented?",
                    "fr": "Quelles conséquences régionales de la perturbation atmosphérique mondiale sont réellement documentées ?",
                },
                "process_type": HistoricalProcess.Type.ENVIRONMENTAL,
                "start": 1815,
                "end": 1816,
                "scope": Assertion.SpatialScope.GLOBAL,
                "point": None,
                "precision": None,
                "status": Assertion.Status.CANDIDATE,
                "confidence": Decimal("0.760"),
                "reason": "Quellenbelegte Einzelaussagen sind vorhanden; die Wirkungsbeziehungen zwischen Eruption, Klima und Gesellschaft benötigen zusätzliche wissenschaftliche Relationsevidenz.",
                "assertions": assertions_for_terms(["Tambora", "Jahr ohne Sommer", "Year Without a Summer"], 1815, 1816),
            },
            {
                "slug": "lisbon-1755",
                "labels": {
                    "de": "Lissabon 1755: Erdbeben, Tsunami und europäische Deutung",
                    "en": "Lisbon 1755: earthquake, tsunami and European interpretation",
                    "fr": "Lisbonne 1755 : séisme, tsunami et interprétation européenne",
                },
                "summaries": {
                    "de": "Ein natur- und ideengeschichtliches Dossier zum Erdbeben und Tsunami von 1755. Der Übergang von Katastrophenbefunden zu philosophischen Deutungen bleibt eine eigene, zu belegende Relation.",
                    "en": "An environmental and intellectual-history dossier on the 1755 earthquake and tsunami. Moving from disaster evidence to philosophical interpretation remains a separate relationship requiring evidence.",
                    "fr": "Un dossier d'histoire environnementale et intellectuelle sur le séisme et le tsunami de 1755. Le passage des faits aux interprétations philosophiques reste une relation distincte à documenter.",
                },
                "questions": {
                    "de": "Wie veränderte die Katastrophe europäische Vorstellungen von Natur, Vorsehung und Staat?",
                    "en": "How did the disaster change European ideas about nature, providence and the state?",
                    "fr": "Comment la catastrophe a-t-elle modifié les idées européennes sur la nature, la providence et l'État ?",
                },
                "process_type": HistoricalProcess.Type.INTELLECTUAL,
                "start": 1755,
                "end": 1755,
                "scope": Assertion.SpatialScope.REGION,
                "point": Point(-9.1393, 38.7223, srid=4326),
                "precision": 80000,
                "status": Assertion.Status.CANDIDATE,
                "confidence": Decimal("0.700"),
                "reason": "Naturereignis und datierte Einzelaussagen sind erschlossen; ideengeschichtliche Wirkungsrelationen müssen noch durch Fachliteratur ergänzt werden.",
                "assertions": assertions_for_terms(["Lissabon", "Lisbon", "Lisbonne"], 1755, 1755),
            },
            {
                "slug": "hamburg-storm-surge-1962",
                "labels": {
                    "de": "Hamburger Sturmflut 1962: Katastrophe, Schutz und Stadtentwicklung",
                    "en": "Hamburg storm surge 1962: disaster, protection and urban development",
                    "fr": "Inondation de Hambourg en 1962 : catastrophe, protection et développement urbain",
                },
                "summaries": {
                    "de": "Ein Dossier zur Sturmflut von 1962 und ihren dokumentierten Schauplätzen. Aussagen zu langfristigem Küstenschutz und Stadtentwicklung benötigen jeweils eigene Wirkungsbelege.",
                    "en": "A dossier on the 1962 storm surge and its documented locations. Claims about long-term flood protection and urban development each require their own impact evidence.",
                    "fr": "Un dossier sur l'inondation de 1962 et ses lieux documentés. Les affirmations sur la protection à long terme et le développement urbain exigent chacune leurs propres preuves.",
                },
                "questions": {
                    "de": "Welche organisatorischen und baulichen Folgen lassen sich direkt auf die Sturmflut zurückführen?",
                    "en": "Which organisational and structural changes can be directly traced to the storm surge?",
                    "fr": "Quels changements organisationnels et structurels peuvent être directement reliés à l'inondation ?",
                },
                "process_type": HistoricalProcess.Type.ENVIRONMENTAL,
                "start": 1962,
                "end": 1962,
                "scope": Assertion.SpatialScope.REGION,
                "point": Point(9.9937, 53.5511, srid=4326),
                "precision": 80000,
                "status": Assertion.Status.CANDIDATE,
                "confidence": Decimal("0.720"),
                "reason": "Die Katastrophe und mehrere Schauplätze sind erschlossen; langfristige Folgen sind noch nicht durch eigenständige Relationsquellen abgesichert.",
                "assertions": assertions_for_terms(["Sturmflut 1962", "Hamburg flood", "Hamburger Sturmflut"], 1962, 1962),
            },
        ]

        created = 0
        skipped = []
        for config in configs:
            if not config["assertions"]:
                skipped.append(config["slug"])
                continue
            process, was_created = self.upsert_process(config)
            created += int(was_created)
            self.upsert_relations(process, config["assertions"], config["status"])

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(configs) - len(skipped)} Dossiers vorhanden ({created} neu)."
            )
        )
        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    "Ohne passende belegte Aussagen übersprungen: " + ", ".join(skipped)
                )
            )

    def upsert_process(self, config):
        identifier = ExternalIdentifier.objects.select_related("entity").filter(
            provider="tripanion-dossier",
            external_id=config["slug"],
        ).first()
        if identifier:
            entity = identifier.entity
            entity.kind = Entity.Kind.PROCESS
            entity.canonical_name = translated(config["labels"])
            entity.labels = config["labels"]
            entity.descriptions = config["summaries"]
            entity.save()
        else:
            entity = Entity.objects.create(
                kind=Entity.Kind.PROCESS,
                canonical_name=translated(config["labels"]),
                labels=config["labels"],
                descriptions=config["summaries"],
            )
            ExternalIdentifier.objects.create(
                entity=entity,
                provider="tripanion-dossier",
                external_id=config["slug"],
                url="https://explore.tripanion.com/",
            )

        process, created = HistoricalProcess.objects.update_or_create(
            entity=entity,
            defaults={
                "process_type": config["process_type"],
                "summary": translated(config["summaries"]),
                "time_start_year": config["start"],
                "time_end_year": config["end"],
                "time_precision": Assertion.Precision.RANGE if config["start"] != config["end"] else Assertion.Precision.YEAR,
                "temporal_scope": Assertion.TemporalScope.BOUNDED,
                "spatial_extent": config["point"],
                "spatial_scope": config["scope"],
                "spatial_precision_meters": config["precision"],
                "status": config["status"],
                "confidence": config["confidence"],
                "confidence_reason": config["reason"],
                "metadata": {
                    "dossier_slug": config["slug"],
                    "dossier_kind": "curated_evidence_path",
                    "summaries": config["summaries"],
                    "editorial_questions": config["questions"],
                    "interpretation_note": {
                        "de": "Die Karten bündeln Evidenz. Nur ausdrücklich als belegt markierte Beziehungen dürfen als Zusammenhang gelesen werden; Gleichzeitigkeit ist kein Kausalitätsbeleg.",
                        "en": "The cards bundle evidence. Only relationships explicitly marked as documented may be read as connections; simultaneity is not causal proof.",
                        "fr": "Les cartes regroupent des preuves. Seules les relations explicitement documentées peuvent être lues comme des liens ; la simultanéité ne prouve pas la causalité.",
                    },
                },
            },
        )
        process.defining_assertions.set(config["assertions"])
        return process, created

    def upsert_relations(self, process, assertions, process_status):
        current_assertion_ids = []
        for assertion in assertions:
            evidence = list(assertion.evidence.filter(relation="supports"))
            if not evidence:
                continue
            current_assertion_ids.append(assertion.id)
            relation, _ = ProcessAssertionRelation.objects.update_or_create(
                process=process,
                assertion=assertion,
                relation_type=ProcessAssertionRelation.Type.MANIFESTS_IN,
                evidence_level=AssertionRelation.EvidenceLevel.DOCUMENTED,
                defaults={
                    "summary": "Die verlinkte Quelle belegt diese einzelne Aussage als Bestandteil des Dossiers; weitergehende Wirkungen werden daraus nicht automatisch abgeleitet.",
                    "time_start_year": assertion.time_start_year,
                    "time_end_year": assertion.time_end_year,
                    "temporal_uncertainty_years": assertion.temporal_uncertainty_years,
                    "spatial_extent": assertion.spatial_extent or assertion.location,
                    "spatial_precision_meters": assertion.spatial_precision_meters,
                    "confidence": min(Decimal(str(assertion.confidence)), Decimal("0.950")),
                    "confidence_reason": "Die Zuordnung stützt sich auf eine direkt zum Befund gespeicherte Evidenz; eine darüber hinausgehende Kausalität ist nicht Teil dieser Relation.",
                    "extraction_method": EXTRACTION_METHOD,
                    "status": (
                        Assertion.Status.VERIFIED
                        if process_status == Assertion.Status.VERIFIED and assertion.status == Assertion.Status.VERIFIED
                        else Assertion.Status.CANDIDATE
                    ),
                    "metadata": {"causal_claim": False},
                },
            )
            relation.evidence.set(evidence)

        ProcessAssertionRelation.objects.filter(
            process=process,
            extraction_method=EXTRACTION_METHOD,
        ).exclude(assertion_id__in=current_assertion_ids).delete()
