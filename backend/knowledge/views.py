import hashlib
import re
from decimal import Decimal

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import connection, transaction
from django.db.models import Count, F, Max, Min, Q, Subquery, Window
from django.db.models.functions import Coalesce, RowNumber
from django.shortcuts import redirect
from django.utils import timezone
import requests
from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .environment import build_climate_series, environment_text
from .environmental_search import environmental_place_radius_km, parse_environmental_query
from .classification import category_summary, time_world_patterns
from .models import (
    Assertion,
    AssertionRelation,
    Entity,
    EnvironmentalDataset,
    EnvironmentalEvent,
    EnvironmentalObservation,
    EnvironmentalRelation,
    Evidence,
    ExplorationContext,
    ExternalIdentifier,
    HistoricalProcess,
    ProcessAssertionRelation,
    ResearchRequest,
    Source,
    WikipediaPortal,
)
from .serializers import (
    AssertionSerializer,
    AssertionRelationSerializer,
    EntitySerializer,
    EnvironmentalDatasetSerializer,
    EnvironmentalEventSerializer,
    EnvironmentalObservationSerializer,
    EnvironmentalRelationSerializer,
    ExplorationContextSerializer,
    HistoricalProcessSerializer,
    ProcessAssertionRelationSerializer,
    ResearchRequestSerializer,
    SourceSerializer,
    WikipediaPortalSerializer,
    validate_language_preferences,
)
from .tasks import run_research_request
from .wikimedia import resolve_wikipedia_entity
from .wikidata import WIKIPEDIA_LANGUAGES, fetch_wikipedia_sitelinks, store_wikipedia_sitelinks


def integer_parameter(request, name, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, int(request.query_params.get(name, default))))
    except (TypeError, ValueError):
        return default


def float_parameter(request, name, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, float(request.query_params.get(name, default))))
    except (TypeError, ValueError):
        return default


class WikidataWikipediaRedirectView(APIView):
    """Redirect a Wikidata item to the best confirmed Wikipedia article."""

    def get(self, request, qid):
        requested = request.query_params.get("languages", "")
        raw_languages = requested.split(",") if requested else [
            part.split(";", 1)[0] for part in request.headers.get("Accept-Language", "").split(",") if part
        ]
        try:
            preferences = validate_language_preferences(raw_languages or ["en"])
        except serializers.ValidationError as error:
            return Response({"detail": error.detail}, status=status.HTTP_400_BAD_REQUEST)
        languages = list(dict.fromkeys([*preferences, *WIKIPEDIA_LANGUAGES]))
        identifier = generics.get_object_or_404(
            ExternalIdentifier.objects.select_related("entity"),
            provider="wikidata",
            external_id=qid,
        )
        stored = {
            item.provider.casefold().removeprefix("wikipedia-"): item.url
            for item in identifier.entity.external_identifiers.filter(provider__startswith="wikipedia-")
            if item.url
        }
        first_stored_index = next(
            (index for index, language in enumerate(languages) if stored.get(language)),
            None,
        )
        if first_stored_index == 0:
            return redirect(stored[languages[0]])

        languages_to_resolve = (
            languages
            if first_stored_index is None
            else languages[:first_stored_index]
        )

        wikidata_url = identifier.url or f"https://www.wikidata.org/wiki/{qid}"
        try:
            resolved = fetch_wikipedia_sitelinks([qid], languages_to_resolve).get(qid, {})
        except requests.RequestException:
            if first_stored_index is not None:
                return redirect(stored[languages[first_stored_index]])
            return redirect(wikidata_url)
        store_wikipedia_sitelinks(identifier.entity, qid, resolved)
        for language in languages:
            if resolved.get(language) or stored.get(language):
                return redirect(resolved.get(language) or stored[language])
        return redirect(wikidata_url)


EVENT_GENERIC_WORDS = {
    "battle",
    "conflict",
    "ereignis",
    "krieg",
    "revolution",
    "schlacht",
    "siege",
    "war",
}


def focus_entity_relevance_filter(exploration_context):
    """Direkte Wissensrelation plus ein vorsichtiger Text-Fallback für lokale Altbestände."""

    event = exploration_context.focus_entity
    relevance = Q(subject=event) | Q(object_entity=event)
    names = [event.canonical_name, *event.labels.values()]
    words = {
        word
        for name in names
        for word in re.findall(r"\w+", str(name).casefold())
        if len(word) >= 6 and word not in EVENT_GENERIC_WORDS
    }
    if words:
        distinctive = max(words, key=len)
        stem = distinctive[: max(6, len(distinctive) - 2)]
        relevance |= Q(subject__canonical_name__icontains=stem) | Q(value_text__icontains=stem)
    return relevance


@api_view(["GET"])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT PostGIS_Version()")
        postgis_version = cursor.fetchone()[0]
    return Response({"status": "ok", "database": "PostgreSQL/PostGIS", "postgis_version": postgis_version})


class KnowledgeBoundsView(APIView):
    """Return the temporal extent currently represented in the knowledge base."""

    def get(self, request):
        years = []
        for model in (Assertion, HistoricalProcess, EnvironmentalEvent, EnvironmentalObservation):
            extent = model.objects.aggregate(
                min_start=Min("time_start_year"),
                min_end=Min("time_end_year"),
                max_start=Max("time_start_year"),
                max_end=Max("time_end_year"),
            )
            years.extend(year for year in extent.values() if year is not None)

        current_year = timezone.now().year
        return Response({
            "time": {
                "min_year": min(years) if years else -1000,
                "max_year": max(years) if years else current_year,
            },
            "distance": {"min_km": 0, "max_km": 20_000},
        })


class ContextView(APIView):
    def get(self, request):
        latitude = float_parameter(request, "lat", 53.836, -90, 90)
        longitude = float_parameter(request, "lon", 9.489, -180, 180)
        year = integer_parameter(request, "year", timezone.now().year, -5_000_000_000, 20_000)
        radius_km = integer_parameter(request, "radius_km", 25, 0, 20_000)
        window_years = integer_parameter(request, "window_years", 10, 0, 1_000_000_000)
        query = request.query_params.get("q", "").strip()
        include_candidates = request.query_params.get("include_candidates", "true").lower() == "true"
        range_start = year - window_years
        range_end = year + window_years
        center = Point(longitude, latitude, srid=4326)

        statuses = [Assertion.Status.VERIFIED, Assertion.Status.DISPUTED]
        if include_candidates:
            statuses.append(Assertion.Status.CANDIDATE)

        assertions = (
            Assertion.objects.filter(
                status__in=statuses,
                location__distance_lte=(center, D(km=radius_km)),
            )
            .filter(Q(time_start_year__isnull=True) | Q(time_start_year__lte=range_end))
            .filter(Q(time_end_year__isnull=True) | Q(time_end_year__gte=range_start))
            .select_related("subject", "object_entity", "location_entity")
            .prefetch_related("subject__external_identifiers", "object_entity__external_identifiers", "evidence__source", "portal_discoveries__portal")
            .annotate(distance=Distance("location", center))
            .order_by("distance", "time_start_year", "-confidence")
        )
        if query:
            assertions = assertions.filter(
                Q(subject__canonical_name__icontains=query)
                | Q(value_text__icontains=query)
                | Q(predicate__icontains=query)
            )

        results = list(assertions[:200])
        coverage = min(1.0, len(results) / 20)
        return Response(
            {
                "query": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "year": year,
                    "range_start": range_start,
                    "range_end": range_end,
                    "radius_km": radius_km,
                    "text": query,
                },
                "coverage": {
                    "score": round(coverage, 2),
                    "level": "gut" if coverage >= 0.7 else "mittel" if coverage >= 0.3 else "gering",
                    "research_recommended": coverage < 0.7,
                },
                "count": len(results),
                "assertions": AssertionSerializer(results, many=True).data,
            }
        )


def exploration_results(exploration_context):
    center = exploration_context.center
    statuses = [Assertion.Status.VERIFIED, Assertion.Status.DISPUTED]
    if exploration_context.include_candidates:
        statuses.append(Assertion.Status.CANDIDATE)

    assertions = (
        Assertion.objects.filter(status__in=statuses)
        .filter(exploration_place_scope_filter(exploration_context))
        .select_related("subject", "object_entity", "location_entity")
        .prefetch_related("subject__external_identifiers", "object_entity__external_identifiers", "evidence__source", "portal_discoveries__portal")
        .annotate(distance=Distance("location", center))
        .distinct()
        .order_by("distance", "time_start_year", "-confidence")
    )
    if not exploration_context.time_unbounded:
        assertions = assertions.filter(
            Q(time_start_year__isnull=True) | Q(time_start_year__lte=exploration_context.time_end_year)
        ).filter(
            Q(time_end_year__isnull=True) | Q(time_end_year__gte=exploration_context.time_start_year)
        )
    if exploration_context.query and exploration_context.query_mode == ExplorationContext.QueryMode.TOPIC:
        assertions = assertions.filter(
            Q(subject__canonical_name__icontains=exploration_context.query)
            | Q(value_text__icontains=exploration_context.query)
            | Q(predicate__icontains=exploration_context.query)
        )
    if exploration_context.focus_entity_id and exploration_context.focus_entity.kind == Entity.Kind.EVENT:
        assertions = assertions.filter(focus_entity_relevance_filter(exploration_context))

    results = list(assertions[:200])
    assertion_ids = [item.id for item in results]
    relations = list(
        AssertionRelation.objects.filter(
            Q(source_assertion_id__in=assertion_ids) | Q(target_assertion_id__in=assertion_ids),
            status__in=statuses,
        )
        .select_related(
            "source_assertion__subject",
            "target_assertion__subject",
        )
        .prefetch_related(
            "source_assertion__subject__external_identifiers",
            "target_assertion__subject__external_identifiers",
            "evidence__source",
        )
        .order_by("-confidence", "evidence_level")[:200]
    )
    coverage = min(1.0, len(results) / 20)
    return {
        "exploration_context": ExplorationContextSerializer(exploration_context).data,
        "coverage": {
            "score": round(coverage, 2),
            "level": "gut" if coverage >= 0.7 else "mittel" if coverage >= 0.3 else "gering",
            "research_recommended": coverage < 0.7,
        },
        "count": len(results),
        "assertions": AssertionSerializer(
            results,
            many=True,
            context={"preferred_languages": exploration_context.languages},
        ).data,
        "assertion_relation_count": len(relations),
        "assertion_relations": AssertionRelationSerializer(
            relations,
            many=True,
            context={"preferred_languages": exploration_context.languages},
        ).data,
    }


def exploration_statuses(exploration_context):
    statuses = [Assertion.Status.VERIFIED, Assertion.Status.DISPUTED]
    if exploration_context.include_candidates:
        statuses.append(Assertion.Status.CANDIDATE)
    return statuses


def exploration_place_scope_filter(exploration_context):
    """Geometrischer Umkreis plus ausdrücklich benannter Orts-/Regionsbezug.

    Ein Ereignis im Grand Harbour gehört zur Geschichte Maltas, selbst wenn der
    Kartenmittelpunkt und ein kleiner Radius es knapp abschneiden. Die exakten
    Ereigniskoordinaten bleiben für Karte und Distanz erhalten.
    """

    if exploration_context.space_unbounded:
        return Q()

    spatial = Q(
        location__distance_lte=(exploration_context.center, D(km=exploration_context.radius_km))
    )
    place_name = exploration_context.place_name.strip()
    if not place_name:
        return spatial
    return (
        spatial
        | Q(location_entity__canonical_name__iexact=place_name)
        | Q(location_entity__labels__icontains=place_name)
        | Q(portal_discoveries__portal__subject_entity__canonical_name__iexact=place_name)
        | Q(portal_discoveries__portal__subject_entity__labels__icontains=place_name)
    )


PLACE_TIMELINE_MAX_RADIUS_KM = 25
PLACE_TIMELINE_MAX_MOMENTS = 300
PLACE_TIMELINE_ASSERTIONS_PER_MOMENT = 4


def exploration_timeline_scope_filter(exploration_context):
    """Der Ortschronik einen stabilen lokalen Bezug geben.

    ``radius_km`` darf für die räumliche Exploration bis auf 1000 km wachsen.
    Würde die Ortschronik denselben Radius verwenden, erschiene bei Agra auch
    Kathmandu. Für ``Ort → Zeit`` gilt deshalb ein eigener, lokaler Deckel.
    Ausdrücklich dem benannten Ort zugeordnete Aussagen bleiben eingeschlossen,
    auch wenn ihre Punktgeometrie den Ortsmittelpunkt nur ungenau abbildet.
    """

    local_radius_km = min(exploration_context.radius_km, PLACE_TIMELINE_MAX_RADIUS_KM)
    spatial = Q(
        location__distance_lte=(exploration_context.center, D(km=local_radius_km))
    )
    place_name = exploration_context.place_name.strip()
    if not place_name:
        return spatial, local_radius_km
    # JSON ``icontains`` searches the complete serialized labels object.  That
    # made short place names match arbitrary word fragments (for example Ense
    # matched Bel*enese*s and Conqu*ense*).  Compare individual locale values
    # exactly instead.
    named_place = (
        Q(subject__canonical_name__iexact=place_name)
        | Q(location_entity__canonical_name__iexact=place_name)
        | (
            Q(portal_discoveries__portal__subject_entity__canonical_name__iexact=place_name)
            & Q(portal_discoveries__title__icontains=place_name)
        )
    )
    for language in {"en", "de", "fr", *exploration_context.languages}:
        named_place |= Q(**{f"subject__labels__{language}__iexact": place_name})
        named_place |= Q(**{f"location_entity__labels__{language}__iexact": place_name})
        named_place |= Q(
            **{
                f"portal_discoveries__portal__subject_entity__labels__{language}__iexact": place_name
            }
        ) & Q(portal_discoveries__title__icontains=place_name)
    return spatial | named_place, local_radius_km


def language_serializer_context(exploration_context):
    return {"preferred_languages": exploration_context.languages}


def prepared_assertions(queryset, center):
    return (
        queryset.select_related("subject", "object_entity", "location_entity")
        .prefetch_related("subject__external_identifiers", "object_entity__external_identifiers", "evidence__source", "portal_discoveries__portal")
        .annotate(distance=Distance("location", center))
        .distinct()
    )


class AssertionRelationListView(APIView):
    """Lesbare, quellengebundene Aussagebeziehungen; keine Beziehung wird aus Zeitnähe impliziert."""

    def get(self, request):
        queryset = AssertionRelation.objects.exclude(status=Assertion.Status.REJECTED)
        assertion_id = request.query_params.get("assertion")
        if assertion_id:
            queryset = queryset.filter(
                Q(source_assertion_id=assertion_id) | Q(target_assertion_id=assertion_id)
            )
        relation_type = request.query_params.get("relation_type")
        if relation_type:
            queryset = queryset.filter(relation_type=relation_type)
        evidence_level = request.query_params.get("evidence_level")
        if evidence_level:
            queryset = queryset.filter(evidence_level=evidence_level)
        relations = list(
            queryset.select_related(
                "source_assertion__subject",
                "target_assertion__subject",
            )
            .prefetch_related(
                "source_assertion__subject__external_identifiers",
                "target_assertion__subject__external_identifiers",
                "evidence__source",
            )
            .order_by("-confidence", "evidence_level")[:500]
        )
        languages = [request.query_params.get("lang", "en"), "en", "de", "fr"]
        return Response(
            {
                "count": len(relations),
                "relations": AssertionRelationSerializer(
                    relations,
                    many=True,
                    context={"preferred_languages": list(dict.fromkeys(languages))},
                ).data,
            }
        )


def process_queryset():
    return (
        HistoricalProcess.objects.select_related("entity")
        .prefetch_related(
            "entity__external_identifiers",
            "defining_assertions__subject__external_identifiers",
            "assertion_relations__process__entity__external_identifiers",
            "assertion_relations__assertion__subject__external_identifiers",
            "assertion_relations__evidence__source",
        )
        .distinct()
    )


class HistoricalProcessListView(APIView):
    """Längerfristige Prozesse mit explizitem Raum, Zeitraum und Evidenzprofil."""

    def get(self, request):
        queryset = process_queryset().exclude(status=Assertion.Status.REJECTED)
        query = request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(entity__canonical_name__icontains=query) | Q(summary__icontains=query)
            )
        process_type = request.query_params.get("process_type")
        if process_type:
            queryset = queryset.filter(process_type=process_type)
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        year = request.query_params.get("year")
        if year:
            try:
                selected_year = int(year)
            except ValueError:
                return Response(
                    {"detail": "year muss eine ganze Jahreszahl sein."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(
                Q(time_start_year__isnull=True) | Q(time_start_year__lte=selected_year)
            ).filter(Q(time_end_year__isnull=True) | Q(time_end_year__gte=selected_year))
        limit = integer_parameter(request, "limit", 100, 1, 500)
        processes = list(queryset.order_by("-confidence", "entity__canonical_name")[:limit])
        languages = [request.query_params.get("lang", "en"), "en", "de", "fr"]
        return Response(
            {
                "count": len(processes),
                "processes": HistoricalProcessSerializer(
                    processes,
                    many=True,
                    context={"preferred_languages": list(dict.fromkeys(languages))},
                ).data,
            }
        )


class HistoricalProcessDetailView(APIView):
    def get(self, request, pk):
        process = generics.get_object_or_404(process_queryset(), pk=pk)
        languages = [request.query_params.get("lang", "en"), "en", "de", "fr"]
        return Response(
            HistoricalProcessSerializer(
                process,
                context={"preferred_languages": list(dict.fromkeys(languages))},
            ).data
        )


class ProcessAssertionRelationListView(APIView):
    """Prozessbezüge; die Evidenzstufe ist ein verpflichtender Teil jeder Antwort."""

    def get(self, request):
        queryset = ProcessAssertionRelation.objects.exclude(status=Assertion.Status.REJECTED)
        process_id = request.query_params.get("process")
        if process_id:
            queryset = queryset.filter(process_id=process_id)
        assertion_id = request.query_params.get("assertion")
        if assertion_id:
            queryset = queryset.filter(assertion_id=assertion_id)
        relation_type = request.query_params.get("relation_type")
        if relation_type:
            queryset = queryset.filter(relation_type=relation_type)
        evidence_level = request.query_params.get("evidence_level")
        if evidence_level:
            queryset = queryset.filter(evidence_level=evidence_level)
        relations = list(
            queryset.select_related("process__entity", "assertion__subject")
            .prefetch_related(
                "process__entity__external_identifiers",
                "assertion__subject__external_identifiers",
                "evidence__source",
            )
            .order_by("-confidence", "evidence_level")[:500]
        )
        languages = [request.query_params.get("lang", "en"), "en", "de", "fr"]
        return Response(
            {
                "count": len(relations),
                "relations": ProcessAssertionRelationSerializer(
                    relations,
                    many=True,
                    context={"preferred_languages": list(dict.fromkeys(languages))},
                ).data,
            }
        )


class ExplorationContextProcessesView(APIView):
    """Prozesse, die im gewählten Raum und Zeitraum durch Aussagen sichtbar werden."""

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        statuses = exploration_statuses(exploration_context)
        local_assertions = Assertion.objects.filter(status__in=statuses).filter(
            exploration_place_scope_filter(exploration_context)
        )
        queryset = process_queryset().filter(status__in=statuses)
        if not exploration_context.time_unbounded:
            local_assertions = local_assertions.filter(
                Q(time_start_year__isnull=True) | Q(time_start_year__lte=exploration_context.time_end_year)
            ).filter(
                Q(time_end_year__isnull=True) | Q(time_end_year__gte=exploration_context.time_start_year)
            )
            queryset = queryset.filter(
                Q(time_start_year__isnull=True) | Q(time_start_year__lte=exploration_context.time_end_year)
            ).filter(
                Q(time_end_year__isnull=True) | Q(time_end_year__gte=exploration_context.time_start_year)
            )
        local_assertions = local_assertions.values("pk")
        process_scope = (
            Q(defining_assertions__in=local_assertions)
            | Q(assertion_relations__assertion__in=local_assertions)
            | Q(spatial_scope=Assertion.SpatialScope.GLOBAL)
        )
        if not exploration_context.space_unbounded:
            process_scope |= Q(
                spatial_extent__dwithin=(
                    exploration_context.center,
                    D(km=exploration_context.radius_km),
                )
            )
        queryset = queryset.filter(process_scope).distinct()
        processes = list(queryset.order_by("-confidence", "entity__canonical_name")[:100])
        level_counts = {
            level: ProcessAssertionRelation.objects.filter(
                process__in=processes,
                evidence_level=level,
                status__in=statuses,
            ).count()
            for level, _label in AssertionRelation.EvidenceLevel.choices
        }
        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "count": len(processes),
                "evidence_levels": level_counts,
                "interpretation_note": (
                    "Gleichzeitigkeit und automatische Ähnlichkeit sind Hinweise, aber kein Beleg für einen Zusammenhang."
                ),
                "processes": HistoricalProcessSerializer(
                    processes,
                    many=True,
                    context=language_serializer_context(exploration_context),
                ).data,
            }
        )


def persist_resolved_event(resolved):
    qid = resolved.get("qid")
    external = (
        ExternalIdentifier.objects.select_related("entity").filter(provider="wikidata", external_id=qid).first()
        if qid
        else None
    )
    if external:
        entity = external.entity
        external.url = f"https://www.wikidata.org/wiki/{qid}"
        external.save(update_fields=["url"])
        entity.kind = Entity.Kind.EVENT
        entity.canonical_name = resolved["title"]
        entity.labels = {**entity.labels, resolved["language"]: resolved["title"]}
        entity.descriptions = {
            **entity.descriptions,
            **({resolved["language"]: resolved["description"]} if resolved.get("description") else {}),
        }
        entity.save(update_fields=["kind", "canonical_name", "labels", "descriptions", "updated_at"])
    else:
        entity = Entity.objects.create(
            kind=Entity.Kind.EVENT,
            canonical_name=resolved["title"],
            labels={resolved["language"]: resolved["title"]},
            descriptions={resolved["language"]: resolved["description"]} if resolved.get("description") else {},
        )
        if qid:
            ExternalIdentifier.objects.create(
                entity=entity,
                provider="wikidata",
                external_id=qid,
                url=f"https://www.wikidata.org/wiki/{qid}",
            )

    page = resolved.get("page", {})
    page_id = str(page.get("pageid", ""))
    if page_id:
        ExternalIdentifier.objects.get_or_create(
            entity=entity,
            provider=f"wikipedia-{resolved['language']}",
            external_id=page_id,
            defaults={"url": resolved.get("page_url", "")},
        )
    source, _ = Source.objects.update_or_create(
        provider=f"Wikipedia ({resolved['language']})",
        record_id=page_id or (qid or resolved["title"]),
        url=resolved.get("page_url") or f"https://www.wikidata.org/wiki/{qid}",
        defaults={
            "title": resolved["title"],
            "source_type": Source.Type.ENCYCLOPEDIA,
            "language": resolved["language"],
            "license_name": "CC BY-SA – siehe Artikelseite",
            "license_url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de",
            "publisher": "Wikimedia Foundation / Wikipedia community",
            "retrieved_at": timezone.now(),
            "metadata": {
                "wikidata_id": qid,
                "thumbnail_url": resolved.get("image_url", ""),
                "resolver": "first-search-result-v2",
            },
        },
    )
    start_year = resolved.get("start_year")
    end_year = resolved.get("end_year")
    if start_year is not None:
        digest = hashlib.sha256(f"{qid or entity.id}|event-period|{start_year}|{end_year}".encode()).hexdigest()
        assertion, _ = Assertion.objects.get_or_create(
            fingerprint=digest,
            defaults={
                "subject": entity,
                "predicate": "event-period",
                "value_text": (resolved.get("description") or resolved.get("extract") or resolved["title"])[:1800],
                "time_start_year": start_year,
                "time_end_year": end_year or start_year,
                "time_precision": Assertion.Precision.RANGE if end_year != start_year else Assertion.Precision.YEAR,
                "status": Assertion.Status.CANDIDATE,
                "confidence": Decimal("0.90") if qid else Decimal("0.72"),
                "extraction_method": "wikimedia-event-resolver-v1",
            },
        )
        Evidence.objects.get_or_create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.SUPPORTS,
            defaults={
                "locator": "Einleitungsdaten und strukturierte Wikidata-Zeitangaben",
                "excerpt": (resolved.get("description") or resolved.get("extract") or "")[:700],
                "confidence": assertion.confidence,
            },
        )
    return entity


class ExplorationContextListCreateView(generics.CreateAPIView):
    serializer_class = ExplorationContextSerializer


class ExplorationContextDetailView(APIView):
    def get_object(self, pk, lock=False):
        queryset = ExplorationContext.objects
        if lock:
            queryset = queryset.select_for_update()
        return generics.get_object_or_404(queryset, pk=pk)

    def get(self, request, pk):
        return Response(ExplorationContextSerializer(self.get_object(pk)).data)

    @transaction.atomic
    def patch(self, request, pk):
        instance = self.get_object(pk, lock=True)
        supplied_version = request.data.get("base_version")
        try:
            version_conflict = supplied_version is not None and int(supplied_version) != instance.version
        except (TypeError, ValueError):
            return Response({"base_version": ["Ungültige Versionsnummer."]}, status=status.HTTP_400_BAD_REQUEST)
        if version_conflict:
            return Response(
                {
                    "detail": "Der Raum-Zeit-Kontext wurde zwischenzeitlich verändert.",
                    "exploration_context": ExplorationContextSerializer(instance).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        serializer = ExplorationContextSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ExplorationContextResultsView(APIView):
    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        return Response(exploration_results(exploration_context))


class ExplorationContextTimelineView(APIView):
    """Die Zeitachse am gewählten Ort, bewusst unabhängig vom aktuellen Fokusjahr."""

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        place_scope, local_radius_km = exploration_timeline_scope_filter(exploration_context)
        assertions = (
            Assertion.objects.filter(
                status__in=exploration_statuses(exploration_context),
                time_start_year__isnull=False,
            )
            .filter(place_scope)
        )
        if exploration_context.query_mode == ExplorationContext.QueryMode.TOPIC and exploration_context.query:
            assertions = assertions.filter(
                Q(subject__canonical_name__icontains=exploration_context.query)
                | Q(value_text__icontains=exploration_context.query)
                | Q(predicate__icontains=exploration_context.query)
            )
        filtered_by_event = bool(
            exploration_context.focus_entity_id
            and exploration_context.focus_entity.kind == Entity.Kind.EVENT
        )
        if filtered_by_event:
            assertions = assertions.filter(focus_entity_relevance_filter(exploration_context))
        # Portal joins may reach the same assertion through several articles.
        # Deduplicate primary keys before adding window functions; otherwise the
        # row number itself makes formerly identical join rows distinct.
        assertion_ids = assertions.order_by().values("pk").distinct()
        # Limit representatives per date, not raw assertions. A busy recent year
        # must never consume the complete result window and hide older milestones.
        assertions = (
            prepared_assertions(
                Assertion.objects.filter(pk__in=Subquery(assertion_ids)),
                exploration_context.center,
            )
            .annotate(timeline_end_year=Coalesce("time_end_year", "time_start_year"))
            .annotate(
                timeline_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("time_start_year"), F("timeline_end_year")],
                    order_by=[
                        F("distance").asc(nulls_last=True),
                        F("confidence").desc(),
                        F("id").asc(),
                    ],
                ),
                timeline_moment_count=Window(
                    expression=Count("id"),
                    partition_by=[F("time_start_year"), F("timeline_end_year")],
                ),
            )
            .filter(timeline_rank__lte=PLACE_TIMELINE_ASSERTIONS_PER_MOMENT)
            .order_by("-time_start_year", "-timeline_end_year", "timeline_rank")
        )
        items = list(
            assertions[
                : (PLACE_TIMELINE_MAX_MOMENTS + 1)
                * PLACE_TIMELINE_ASSERTIONS_PER_MOMENT
            ]
        )
        serialized = AssertionSerializer(
            items,
            many=True,
            context=language_serializer_context(exploration_context),
        ).data
        moments = {}
        for assertion, item in zip(items, serialized):
            end_year = assertion.time_end_year or assertion.time_start_year
            key = (assertion.time_start_year, end_year)
            if key not in moments:
                moments[key] = {
                    "year": assertion.time_start_year,
                    "end_year": end_year,
                    "precision": assertion.time_precision,
                    "count": assertion.timeline_moment_count,
                    "assertions": [],
                }
            moment = moments[key]
            if len(moment["assertions"]) < 4:
                moment["assertions"].append(item)

        selected_moments = list(moments.values())[:PLACE_TIMELINE_MAX_MOMENTS]

        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "count": sum(moment["count"] for moment in selected_moments),
                "moment_count": len(selected_moments),
                "is_truncated": len(moments) > PLACE_TIMELINE_MAX_MOMENTS,
                "filter": (
                    {"type": "event", "name": exploration_context.focus_entity.canonical_name}
                    if filtered_by_event
                    else None
                ),
                "scope": {
                    "type": "place_history",
                    "local_radius_km": local_radius_km,
                    "exploration_radius_km": exploration_context.radius_km,
                },
                "reference_place": {
                    "name": exploration_context.place_name,
                    "center": {
                        "latitude": exploration_context.center.y,
                        "longitude": exploration_context.center.x,
                    },
                    "radius_km": local_radius_km,
                },
                "moments": selected_moments,
            }
        )


class ExplorationContextTimeWorldView(APIView):
    """Aussagen im unabhängigen Schnittpunkt von Raum- und Zeitfokus."""

    SCOPE_LABELS = {
        "local": "Lokal",
        "regional": "Regional",
        "macroregional": "Land / Großregion",
        "global": "Global",
    }

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        result_limit = integer_parameter(request, "limit", 500, 1, 1000)
        assertions = Assertion.objects.filter(
            status__in=exploration_statuses(exploration_context),
            location__isnull=False,
            time_start_year__isnull=False,
        )
        if not exploration_context.time_unbounded:
            assertions = assertions.filter(
                time_start_year__lte=exploration_context.time_end_year,
            ).filter(
                Q(time_end_year__gte=exploration_context.time_start_year)
                | Q(time_end_year__isnull=True, time_start_year__gte=exploration_context.time_start_year)
            )
        if not exploration_context.space_unbounded:
            assertions = assertions.filter(
                location__distance_lte=(
                    exploration_context.center,
                    D(km=exploration_context.radius_km),
                )
            )
        if exploration_context.query_mode == ExplorationContext.QueryMode.TOPIC and exploration_context.query:
            assertions = assertions.filter(
                Q(subject__canonical_name__icontains=exploration_context.query)
                | Q(value_text__icontains=exploration_context.query)
                | Q(predicate__icontains=exploration_context.query)
            )
        total_count = assertions.values(
            "subject_id",
            "time_start_year",
            "time_end_year",
        ).distinct().count()
        assertions = prepared_assertions(assertions, exploration_context.center).annotate(
            support_evidence_count=Count(
                "evidence",
                filter=Q(evidence__relation=Evidence.Relation.SUPPORTS),
                distinct=True,
            ),
        ).order_by("-confidence", "-support_evidence_count", "distance", "-updated_at")
        candidates = list(assertions[: min(result_limit * 4, 4000)])
        seen_events = set()
        items = []
        for assertion in candidates:
            event_key = (assertion.subject_id, assertion.time_start_year, assertion.time_end_year)
            if event_key in seen_events:
                continue
            seen_events.add(event_key)
            items.append(assertion)
            if len(items) >= result_limit:
                break
        serialized = AssertionSerializer(
            items,
            many=True,
            context=language_serializer_context(exploration_context),
        ).data
        scopes = {
            key: {"key": key, "label": label, "count": 0, "assertions": []}
            for key, label in self.SCOPE_LABELS.items()
        }
        for assertion, item in zip(items, serialized):
            distance_km = assertion.distance.km
            if distance_km <= 25:
                scope = "local"
            elif distance_km <= 250:
                scope = "regional"
            elif distance_km <= 1500:
                scope = "macroregional"
            else:
                scope = "global"
            item["spatial_scope"] = scope
            scopes[scope]["count"] += 1
            scopes[scope]["assertions"].append(item)

        classified, categories = category_summary(items)

        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "count": len(items),
                "total_count": total_count,
                "limit": result_limit,
                "truncated": total_count > len(items),
                "selection": {
                    "focus_year": exploration_context.time_focus_year,
                    "start_year": None if exploration_context.time_unbounded else exploration_context.time_start_year,
                    "end_year": None if exploration_context.time_unbounded else exploration_context.time_end_year,
                    "window_years": None if exploration_context.time_unbounded else exploration_context.time_window_years * 2,
                    "time_unbounded": exploration_context.time_unbounded,
                    "window_semantics": "unbounded" if exploration_context.time_unbounded else "centered",
                    "reference_place": {
                        "name": exploration_context.place_name,
                        "center": {
                            "latitude": exploration_context.center.y,
                            "longitude": exploration_context.center.x,
                        },
                        "radius_km": None if exploration_context.space_unbounded else exploration_context.radius_km,
                        "space_unbounded": exploration_context.space_unbounded,
                    },
                },
                "result_semantics": "dated_assertions_not_causal_events",
                "filter_semantics": "intersection_of_independent_time_and_space_axes",
                "ranking_semantics": "confidence_then_supporting_evidence_then_distance",
                "scope_basis": "Harte Raum- und Zeitfilter; die Einteilung beschreibt anschließend die Entfernung vom gewählten Ort.",
                "categories": categories,
                "patterns": time_world_patterns(classified),
                "scopes": list(scopes.values()),
            }
        )


class ExplorationContextLivingConditionsView(APIView):
    """Umweltbedingungen im gewählten Raum-Zeit-Fenster, getrennt nach Befund und möglicher Folge."""

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        statuses = exploration_statuses(exploration_context)
        time_filter = Q()
        if not exploration_context.time_unbounded:
            time_filter = Q(
                time_start_year__lte=exploration_context.time_end_year,
                time_end_year__gte=exploration_context.time_start_year,
            )
        wide_scopes = [
            EnvironmentalObservation.SpatialScope.HEMISPHERIC,
            EnvironmentalObservation.SpatialScope.GLOBAL,
        ]
        spatial_filter = Q()
        if not exploration_context.space_unbounded:
            spatial_filter = Q(spatial_scope__in=wide_scopes) | Q(
                geometry__distance_lte=(exploration_context.center, D(km=exploration_context.radius_km))
            )
        observations = list(
            EnvironmentalObservation.objects.filter(time_filter, spatial_filter, status__in=statuses)
            .select_related("dataset", "dataset__source", "event")
            .prefetch_related("evidence__source")
            .order_by("spatial_scope", "-confidence", "variable")[:160]
        )

        influencing_event_ids = [item.event_id for item in observations if item.event_id]
        local_event_filter = Q()
        if not exploration_context.space_unbounded:
            local_event_filter = Q(
                geometry__distance_lte=(exploration_context.center, D(km=exploration_context.radius_km))
            )
        events_queryset = (
            EnvironmentalEvent.objects.filter(status__in=statuses)
            .filter(Q(id__in=influencing_event_ids) | (time_filter & local_event_filter))
            .select_related("dataset", "dataset__source")
            .prefetch_related("evidence__source")
            .annotate(distance=Distance("geometry", exploration_context.center))
            .order_by("-confidence", "event_type", "name")
        )
        events = list(events_queryset[:80])
        event_ids = [item.id for item in events]

        relations_queryset = EnvironmentalRelation.objects.filter(
            environmental_event_id__in=event_ids,
            status__in=statuses,
        )
        if not exploration_context.space_unbounded:
            relations_queryset = relations_queryset.filter(
                historical_assertion__location__distance_lte=(
                    exploration_context.center,
                    D(km=exploration_context.radius_km),
                )
            )
        relations = list(
            relations_queryset
            .select_related(
                "environmental_event",
                "environmental_event__dataset",
                "environmental_event__dataset__source",
                "historical_assertion",
                "historical_assertion__subject",
            )
            .prefetch_related(
                "evidence__source",
                "environmental_event__evidence__source",
                "historical_assertion__evidence__source",
                "historical_assertion__subject__external_identifiers",
            )
            .order_by("-confidence", "relation_type")[:80]
        )

        dataset_ids = {
            *[item.dataset_id for item in events if item.dataset_id],
            *[item.dataset_id for item in observations if item.dataset_id],
        }
        datasets = list(
            EnvironmentalDataset.objects.filter(id__in=dataset_ids)
            .select_related("source")
            .order_by("provider", "title")
        )
        serializer_context = language_serializer_context(exploration_context)
        climate_series, climate_warnings = build_climate_series(exploration_context)
        if relations:
            assessment = environment_text(exploration_context, "assessment_relations")
        elif events or observations or climate_series:
            assessment = environment_text(exploration_context, "assessment_conditions")
        else:
            assessment = environment_text(exploration_context, "assessment_empty")

        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "reference_place": {
                    "name": exploration_context.place_name,
                    "center": {
                        "latitude": exploration_context.center.y,
                        "longitude": exploration_context.center.x,
                    },
                    "radius_km": None if exploration_context.space_unbounded else exploration_context.radius_km,
                    "space_unbounded": exploration_context.space_unbounded,
                },
                "time_range": {
                    "focus_year": exploration_context.time_focus_year,
                    "start_year": None if exploration_context.time_unbounded else exploration_context.time_start_year,
                    "end_year": None if exploration_context.time_unbounded else exploration_context.time_end_year,
                    "window_years": None if exploration_context.time_unbounded else exploration_context.time_window_years * 2,
                    "time_unbounded": exploration_context.time_unbounded,
                },
                "assessment": assessment,
                "uncertainty_note": environment_text(exploration_context, "causality"),
                "event_count": len(events),
                "events": EnvironmentalEventSerializer(events, many=True, context=serializer_context).data,
                "observation_count": len(observations),
                "observations": EnvironmentalObservationSerializer(
                    observations,
                    many=True,
                    context=serializer_context,
                ).data,
                "relation_count": len(relations),
                "relations": EnvironmentalRelationSerializer(
                    relations,
                    many=True,
                    context=serializer_context,
                ).data,
                "datasets": EnvironmentalDatasetSerializer(datasets, many=True).data,
                "climate_series_count": len(climate_series),
                "climate_series": climate_series,
                "climate_warnings": climate_warnings,
                "storage_policy": (
                    "PostgreSQL/PostGIS speichert Metadaten und räumlich-zeitliche Ausschnitte. "
                    "NetCDF und GeoTIFF verbleiben extern oder als Cloud-optimierte GeoTIFFs im Objektspeicher."
                ),
            }
        )


class ExplorationContextEnvironmentalEventsView(APIView):
    """Zeitlich offene Naturereignissuche, global oder um einen benannten Ort."""

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        event_types = list(exploration_context.environmental_event_types or [])
        queryset = EnvironmentalEvent.objects.filter(status__in=exploration_statuses(exploration_context))
        if event_types:
            queryset = queryset.filter(event_type__in=event_types)
        place_filter_applied = bool(exploration_context.environmental_place_name)
        place_filter_method = None
        if place_filter_applied:
            # Country catalogues often carry an explicit affected-country
            # assignment. Prefer it over a large centroid radius so a query
            # such as "Tsunami Thailand" does not become a list of events in
            # every neighbouring country. Other places and datasets retain
            # the geometry-based fallback.
            country_matches = queryset.filter(
                metadata__country__iexact=exploration_context.environmental_place_name,
            )
            if exploration_context.radius_km >= 500 and country_matches.exists():
                queryset = country_matches.filter(geometry__isnull=False).annotate(
                    distance=Distance("geometry", exploration_context.center),
                )
                place_filter_method = "source_country"
            else:
                queryset = queryset.filter(
                    geometry__distance_lte=(
                        exploration_context.center,
                        D(km=exploration_context.radius_km),
                    )
                ).annotate(distance=Distance("geometry", exploration_context.center))
                place_filter_method = "radius"

        summary = queryset.aggregate(
            count=Count("id"),
            first_year=Min("time_start_year"),
            last_year=Max("time_end_year"),
        )
        category_counts = {
            item["event_type"]: item["count"]
            for item in queryset.values("event_type").annotate(count=Count("id"))
        }
        limit = integer_parameter(request, "limit", 300, 1, 500)
        events = list(
            queryset.select_related("dataset", "dataset__source")
            .prefetch_related("evidence__source")
            .order_by("-time_end_year", "-time_start_year", "-confidence", "name")[:limit]
        )
        type_labels = dict(EnvironmentalEvent.Type.choices)
        serializer_context = language_serializer_context(exploration_context)

        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "selection": {
                    "query": exploration_context.query,
                    "scope": "place" if place_filter_applied else "global",
                    "time_scope": "all",
                    "place_filter_applied": place_filter_applied,
                    "place_filter_method": place_filter_method,
                    "time_filter_applied": False,
                    "event_types": event_types,
                    "reference_place": (
                        {
                            "name": exploration_context.environmental_place_name,
                            "center": {
                                "latitude": exploration_context.center.y,
                                "longitude": exploration_context.center.x,
                            },
                            "radius_km": exploration_context.radius_km,
                        }
                        if place_filter_applied
                        else None
                    ),
                },
                "count": summary["count"],
                "returned_count": len(events),
                "truncated": summary["count"] > len(events),
                "georeferenced_count": queryset.exclude(geometry__isnull=True).count(),
                "time_extent": {
                    "start_year": summary["first_year"],
                    "end_year": summary["last_year"],
                },
                "categories": [
                    {
                        "key": event_type,
                        "label": type_labels.get(event_type, event_type),
                        "count": category_counts.get(event_type, 0),
                    }
                    for event_type in event_types or category_counts
                ],
                "events": EnvironmentalEventSerializer(
                    events,
                    many=True,
                    context=serializer_context,
                ).data,
            }
        )


class ExplorationContextEventDossierView(APIView):
    """Das Ereignis als Brücke: Verlauf, Schauplätze und Bezug zum Ausgangsort."""

    def get(self, request, pk):
        exploration_context = generics.get_object_or_404(
            ExplorationContext.objects.select_related("focus_entity").prefetch_related(
                "focus_entity__external_identifiers"
            ),
            pk=pk,
        )
        event = exploration_context.focus_entity
        if event is None or event.kind != Entity.Kind.EVENT:
            return Response(
                {"detail": "In diesem Raum-Zeit-Kontext ist kein Ereignis ausgewählt."},
                status=status.HTTP_404_NOT_FOUND,
            )

        statuses = exploration_statuses(exploration_context)
        start_year = exploration_context.event_start_year
        end_year = exploration_context.event_end_year or start_year
        related = Assertion.objects.filter(status__in=statuses).filter(Q(subject=event) | Q(object_entity=event))
        if start_year is not None:
            related = related.filter(Q(time_start_year__isnull=True) | Q(time_start_year__lte=end_year)).filter(
                Q(time_end_year__isnull=True) | Q(time_end_year__gte=start_year)
            )
        related_items = list(
            prepared_assertions(related, exploration_context.center).order_by(
                "time_start_year", "distance", "-confidence"
            )[:300]
        )

        unique_places = {}
        for item in related_items:
            if item.location is None or item.subject_id == event.id:
                continue
            key = (item.subject.canonical_name.casefold(), item.time_start_year, item.time_end_year)
            previous = unique_places.get(key)
            if previous is None or item.confidence > previous.confidence:
                unique_places[key] = item
        places = sorted(
            unique_places.values(),
            key=lambda item: (
                item.time_start_year if item.time_start_year is not None else 10**12,
                item.distance.km if item.distance is not None else 10**12,
            ),
        )
        place_ids = {item.id for item in places}
        words = [word for word in re.findall(r"\w+", event.canonical_name.casefold()) if len(word) >= 5]
        term_filter = Q()
        for word in words:
            stem = word[: max(5, len(word) - 2)]
            term_filter |= Q(subject__canonical_name__icontains=stem)
            term_filter |= Q(value_text__icontains=stem)

        local = Assertion.objects.filter(
            status__in=statuses,
            location__distance_lte=(exploration_context.center, D(km=exploration_context.radius_km)),
        ).exclude(id__in=place_ids)
        if start_year is not None:
            local = local.filter(Q(time_start_year__isnull=True) | Q(time_start_year__lte=end_year)).filter(
                Q(time_end_year__isnull=True) | Q(time_end_year__gte=start_year)
            )
        if words:
            local = local.filter(term_filter)
        else:
            local = local.none()
        local_items = list(
            prepared_assertions(local, exploration_context.center).order_by("distance", "time_start_year", "-confidence")[:80]
        )

        chronology_items = [
            item for item in related_items if item.subject_id == event.id and item.time_start_year is not None
        ] + [item for item in places if item.time_start_year is not None]
        moments = {}
        serialization_context = language_serializer_context(exploration_context)
        chronology_serialized = AssertionSerializer(
            chronology_items,
            many=True,
            context=serialization_context,
        ).data
        for assertion, item in zip(chronology_items, chronology_serialized):
            finish = assertion.time_end_year or assertion.time_start_year
            key = (assertion.time_start_year, finish)
            moment = moments.setdefault(
                key,
                {
                    "year": assertion.time_start_year,
                    "end_year": finish,
                    "count": 0,
                    "assertions": [],
                },
            )
            moment["count"] += 1
            if len(moment["assertions"]) < 5:
                moment["assertions"].append(item)

        external_links = list(event.external_identifiers.all())
        source_links = [
            {"provider": item.provider, "url": item.url, "external_id": item.external_id}
            for item in external_links
            if item.url
        ]
        description = next(
            (
                event.descriptions[language]
                for language in exploration_context.languages
                if event.descriptions.get(language)
            ),
            next(iter(event.descriptions.values()), ""),
        )
        return Response(
            {
                "exploration_context": ExplorationContextSerializer(exploration_context).data,
                "event": EntitySerializer(event, context=serialization_context).data,
                "description": description,
                "start_year": start_year,
                "end_year": end_year,
                "temporal_confidence": 0.9 if start_year is not None else 0.45,
                "uncertainty_note": (
                    "Der Zeitraum stammt aus Wikipedia/Wikidata. Verknüpfte Schauplätze sind automatisch gefundene Kandidaten und müssen einzeln belegt werden."
                ),
                "sources": source_links,
                "moment_count": len(moments),
                "moments": list(moments.values()),
                "place_count": len(places),
                "places": AssertionSerializer(places, many=True, context=serialization_context).data,
                "local_count": len(local_items),
                "local_assertions": AssertionSerializer(
                    local_items,
                    many=True,
                    context=serialization_context,
                ).data,
                "reference_place": {
                    "name": exploration_context.place_name,
                    "center": {
                        "latitude": exploration_context.center.y,
                        "longitude": exploration_context.center.x,
                    },
                    "radius_km": exploration_context.radius_km,
                },
            }
        )


class ExplorationContextResolveView(APIView):
    def post(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        query = str(request.data.get("query", "")).strip()
        if not query:
            return Response({"query": ["Bitte einen Ort oder ein Thema eingeben."]}, status=status.HTTP_400_BAD_REQUEST)
        if len(query) > 500:
            return Response({"query": ["Die Eingabe darf höchstens 500 Zeichen enthalten."]}, status=status.HTTP_400_BAD_REQUEST)

        supplied_version = request.data.get("base_version")
        try:
            if supplied_version is not None and int(supplied_version) != exploration_context.version:
                return Response(
                    {
                        "detail": "Der Raum-Zeit-Kontext wurde zwischenzeitlich verändert.",
                        "exploration_context": ExplorationContextSerializer(exploration_context).data,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        except (TypeError, ValueError):
            return Response({"base_version": ["Ungültige Versionsnummer."]}, status=status.HTTP_400_BAD_REQUEST)

        environmental_query = parse_environmental_query(query)
        environmental_event_types = list(environmental_query["event_types"])
        environmental_place = None
        resolved = None
        if environmental_event_types and environmental_query["place_query"]:
            try:
                place_candidate = resolve_wikipedia_entity(
                    environmental_query["place_query"],
                    exploration_context.languages,
                    reference_center=exploration_context.center,
                )
            except requests.RequestException:
                return Response(
                    {"detail": "Die Ortsauflösung über Wikipedia ist derzeit nicht erreichbar."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            if place_candidate and place_candidate["kind"] == "place":
                environmental_place = place_candidate
            else:
                environmental_event_types = []

        if not environmental_event_types:
            try:
                resolved = resolve_wikipedia_entity(
                    query,
                    exploration_context.languages,
                    reference_center=exploration_context.center,
                )
            except requests.RequestException:
                return Response(
                    {"detail": "Die Ortsauflösung über Wikipedia ist derzeit nicht erreichbar."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        with transaction.atomic():
            locked = ExplorationContext.objects.select_for_update().get(pk=pk)
            if locked.version != exploration_context.version:
                return Response(
                    {
                        "detail": "Der Raum-Zeit-Kontext wurde zwischenzeitlich verändert.",
                        "exploration_context": ExplorationContextSerializer(locked).data,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            locked.query = query
            locked.version += 1
            if environmental_event_types:
                locked.query_mode = ExplorationContext.QueryMode.ENVIRONMENT
                locked.anchor_mode = ExplorationContext.AnchorMode.ENVIRONMENT
                locked.environmental_event_types = environmental_event_types
                locked.environmental_place_name = ""
                locked.topics = []
                locked.focus_entity = None
                locked.event_start_year = None
                locked.event_end_year = None
                if environmental_place:
                    locked.place_name = environmental_place["title"]
                    locked.environmental_place_name = environmental_place["title"]
                    locked.center = Point(
                        environmental_place["longitude"],
                        environmental_place["latitude"],
                        srid=4326,
                    )
                    locked.map_zoom = 9
                    locked.radius_km = environmental_place_radius_km(environmental_place)
            elif resolved and resolved["kind"] == "place":
                # Keep the user's familiar wording in the interface. The resolved
                # Wikipedia title is still returned separately as provenance.
                locked.place_name = query
                locked.center = Point(resolved["longitude"], resolved["latitude"], srid=4326)
                locked.map_zoom = 14
                locked.query_mode = ExplorationContext.QueryMode.PLACE
                locked.anchor_mode = ExplorationContext.AnchorMode.SPACE
                locked.topics = []
                locked.focus_entity = None
                locked.event_start_year = None
                locked.event_end_year = None
                locked.environmental_event_types = []
                locked.environmental_place_name = ""
            elif resolved and resolved["kind"] == "event":
                event = persist_resolved_event(resolved)
                locked.query = resolved["title"]
                locked.query_mode = ExplorationContext.QueryMode.EVENT
                locked.anchor_mode = ExplorationContext.AnchorMode.EVENT
                locked.focus_entity = event
                locked.event_start_year = resolved.get("start_year")
                locked.event_end_year = resolved.get("end_year") or resolved.get("start_year")
                locked.topics = [resolved["title"]]
                locked.environmental_event_types = []
                locked.environmental_place_name = ""
                if locked.event_start_year is not None:
                    event_end = locked.event_end_year or locked.event_start_year
                    locked.time_focus_year = (locked.event_start_year + event_end) // 2
                    locked.time_window_years = max(
                        locked.time_focus_year - locked.event_start_year,
                        event_end - locked.time_focus_year,
                    )
            else:
                locked.query_mode = ExplorationContext.QueryMode.TOPIC
                locked.topics = [query]
                locked.anchor_mode = ExplorationContext.AnchorMode.SPACE
                locked.focus_entity = None
                locked.event_start_year = None
                locked.event_end_year = None
                locked.environmental_event_types = []
                locked.environmental_place_name = ""
            locked.save()

        resolved_as = "environment" if environmental_event_types else (resolved["kind"] if resolved else "topic")
        return Response(
            {
                "resolved_as": resolved_as,
                "place": (
                    {key: resolved[key] for key in ("title", "language", "latitude", "longitude")}
                    if resolved_as == "place"
                    else None
                ),
                "event": (
                    {
                        key: resolved.get(key)
                        for key in ("title", "language", "qid", "description", "start_year", "end_year", "page_url", "image_url")
                    }
                    if resolved_as == "event"
                    else None
                ),
                "environment": (
                    {
                        "event_types": environmental_event_types,
                        "scope": "place" if environmental_place else "global",
                        "time_scope": "all",
                        "place": (
                            {
                                key: environmental_place[key]
                                for key in ("title", "language", "latitude", "longitude")
                            }
                            if environmental_place
                            else None
                        ),
                    }
                    if resolved_as == "environment"
                    else None
                ),
                "exploration_context": ExplorationContextSerializer(locked).data,
            }
        )


class ExplorationContextResearchView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "research"

    def post(self, request, pk):
        exploration_context = generics.get_object_or_404(ExplorationContext, pk=pk)
        if exploration_context.time_unbounded or exploration_context.space_unbounded:
            return Response(
                {
                    "detail": (
                        "Eine unbegrenzte Achse zeigt den vorhandenen Wissensbestand, "
                        "startet aber keine unbeschränkte externe Recherche."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        topics = exploration_context.topics or ([exploration_context.query] if exploration_context.query else ["allgemein"])
        if exploration_context.anchor_mode == ExplorationContext.AnchorMode.TIME:
            topics = ["__time_world__", *topics]
        elif exploration_context.anchor_mode == ExplorationContext.AnchorMode.EVENT and exploration_context.focus_entity_id:
            qid = next(
                (
                    item.external_id
                    for item in exploration_context.focus_entity.external_identifiers.filter(provider="wikidata")
                ),
                "",
            )
            topics = [f"__event__:{qid}", *topics]
        research_request = ResearchRequest.objects.create(
            query=exploration_context.query,
            center=exploration_context.center,
            # The exploration axis may cover the whole globe. External
            # Wikimedia research remains deliberately bounded; broader
            # scopes rank the already stored knowledge instead of issuing a
            # single, excessively large upstream request.
            radius_km=min(max(exploration_context.radius_km, 1), 1000),
            time_start_year=exploration_context.time_start_year,
            time_end_year=exploration_context.time_end_year,
            topics=topics,
            languages=exploration_context.languages,
        )
        run_research_request.delay(str(research_request.id))
        return Response(ResearchRequestSerializer(research_request).data, status=status.HTTP_201_CREATED)


class ResearchListCreateView(generics.ListCreateAPIView):
    serializer_class = ResearchRequestSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "research"

    def get_queryset(self):
        return ResearchRequest.objects.order_by("-last_requested_at")[:100]

    def perform_create(self, serializer):
        research_request = serializer.save()
        run_research_request.delay(str(research_request.id))


class ResearchDetailView(generics.RetrieveAPIView):
    queryset = ResearchRequest.objects.all()
    serializer_class = ResearchRequestSerializer


class EntityListView(generics.ListAPIView):
    serializer_class = EntitySerializer

    def get_queryset(self):
        queryset = Entity.objects.prefetch_related("external_identifiers").order_by("canonical_name")
        query = self.request.query_params.get("q", "").strip()
        return queryset.filter(canonical_name__icontains=query) if query else queryset


class SourceListView(generics.ListAPIView):
    serializer_class = SourceSerializer
    queryset = Source.objects.order_by("-retrieved_at")


class WikipediaPortalListView(generics.ListAPIView):
    serializer_class = WikipediaPortalSerializer

    def get_queryset(self):
        queryset = WikipediaPortal.objects.select_related("subject_entity").order_by("language", "title")
        language = self.request.query_params.get("language", "").strip().casefold()
        scan_status = self.request.query_params.get("status", "").strip().casefold()
        query = self.request.query_params.get("q", "").strip()
        if language:
            queryset = queryset.filter(language=language)
        if scan_status:
            queryset = queryset.filter(scan_status=scan_status)
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query) | Q(subject_entity__canonical_name__icontains=query)
            )
        return queryset
