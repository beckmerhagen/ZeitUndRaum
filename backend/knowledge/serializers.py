import re
import json

from django.contrib.gis.geos import Point
from rest_framework import serializers

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
    ResearchRequest,
    Source,
    PortalArticle,
    WikipediaPortal,
)
from .classification import classify_assertion


LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}$")


def validate_language_preferences(languages):
    normalized = []
    for value in languages:
        language = str(value).strip().casefold().split("-")[0]
        if not LANGUAGE_CODE_PATTERN.fullmatch(language):
            raise serializers.ValidationError(f"Ungültiger Sprachcode: {value}")
        if language not in normalized:
            normalized.append(language)
    if not normalized:
        raise serializers.ValidationError("Mindestens eine Sprache ist erforderlich.")
    return normalized[:4]


def preferred_languages(context):
    return context.get("preferred_languages") or ["de", "en"]


def language_rank(language, preferences):
    try:
        return preferences.index((language or "").casefold())
    except ValueError:
        return len(preferences)


class ExternalIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalIdentifier
        fields = ("provider", "external_id", "url")


class EntitySerializer(serializers.ModelSerializer):
    canonical_name = serializers.SerializerMethodField()
    external_identifiers = ExternalIdentifierSerializer(many=True, read_only=True)

    class Meta:
        model = Entity
        fields = ("id", "kind", "canonical_name", "labels", "descriptions", "external_identifiers")

    def get_canonical_name(self, obj):
        for language in preferred_languages(self.context):
            if obj.labels.get(language):
                return obj.labels[language]
        return obj.canonical_name


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = (
            "id",
            "provider",
            "title",
            "url",
            "record_id",
            "source_type",
            "language",
            "license_name",
            "license_url",
            "publisher",
            "published_at",
            "retrieved_at",
            "metadata",
        )


class EvidenceSerializer(serializers.ModelSerializer):
    source = SourceSerializer(read_only=True)

    class Meta:
        model = Evidence
        fields = ("id", "relation", "locator", "excerpt", "confidence", "source")


class AssertionSerializer(serializers.ModelSerializer):
    subject = EntitySerializer(read_only=True)
    object_entity = EntitySerializer(read_only=True)
    evidence = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    location_entity = EntitySerializer(read_only=True)
    spatial_extent = serializers.SerializerMethodField()
    temporal_extent = serializers.SerializerMethodField()
    integrity = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    discovered_via_portals = serializers.SerializerMethodField()
    content_category = serializers.SerializerMethodField()
    preferred_link = serializers.SerializerMethodField()

    class Meta:
        model = Assertion
        fields = (
            "id",
            "subject",
            "predicate",
            "object_entity",
            "value",
            "value_number",
            "value_min",
            "value_max",
            "value_unit",
            "time_start_year",
            "time_end_year",
            "time_start_month",
            "time_start_day",
            "time_end_month",
            "time_end_day",
            "time_precision",
            "temporal_uncertainty_years",
            "temporal_scope",
            "calendar_model",
            "temporal_note",
            "temporal_extent",
            "location",
            "location_entity",
            "spatial_extent",
            "spatial_scope",
            "distance_km",
            "image_url",
            "spatial_precision_meters",
            "spatial_note",
            "status",
            "knowledge_type",
            "confidence",
            "confidence_reason",
            "extraction_method",
            "metadata",
            "evidence",
            "discovered_via_portals",
            "content_category",
            "preferred_link",
            "integrity",
        )

    def get_location(self, obj):
        if not obj.location:
            return None
        return {"latitude": obj.location.y, "longitude": obj.location.x}

    def get_spatial_extent(self, obj):
        return geometry_geojson(obj.spatial_extent)

    def get_temporal_extent(self, obj):
        return obj.temporal_extent

    def get_integrity(self, obj):
        issues = obj.integrity_issues()
        return {"complete": not issues, "issues": issues}

    def get_distance_km(self, obj):
        distance = getattr(obj, "distance", None)
        return round(distance.km, 2) if distance is not None else None

    def ordered_evidence(self, obj):
        preferences = preferred_languages(self.context)
        return sorted(
            obj.evidence.all(),
            key=lambda item: language_rank(item.source.language, preferences),
        )

    def get_evidence(self, obj):
        return EvidenceSerializer(self.ordered_evidence(obj), many=True, context=self.context).data

    def get_value(self, obj):
        if obj.extraction_method.startswith("wikipedia"):
            for item in self.ordered_evidence(obj):
                if item.excerpt:
                    return item.excerpt
        return obj.display_value

    def get_image_url(self, obj):
        for item in self.ordered_evidence(obj):
            thumbnail_url = item.source.metadata.get("thumbnail_url")
            if thumbnail_url:
                return thumbnail_url
        return None

    def get_discovered_via_portals(self, obj):
        return [
            {
                "language": article.portal.language,
                "portal_title": article.portal.title,
                "portal_url": article.portal.url,
                "article_title": article.title,
                "article_url": article.url,
                "role": "discovery_only",
            }
            for article in obj.portal_discoveries.all()[:12]
        ]

    def get_content_category(self, obj):
        return classify_assertion(obj)

    def get_preferred_link(self, obj):
        preferences = preferred_languages(self.context)
        identifiers = list(obj.subject.external_identifiers.all())
        for language in preferences:
            provider = f"wikipedia-{language}"
            match = next(
                (item for item in identifiers if item.provider.casefold() == provider and item.url),
                None,
            )
            if match:
                return {
                    "kind": "wikipedia_article",
                    "provider": "Wikipedia",
                    "language": language,
                    "url": match.url,
                }

        wikidata = next(
            (
                item
                for item in identifiers
                if item.provider.casefold() == "wikidata" and re.fullmatch(r"Q\d+", item.external_id)
            ),
            None,
        )
        if wikidata:
            language = next(
                (item for item in preferences if LANGUAGE_CODE_PATTERN.fullmatch(item)),
                "en",
            )
            return {
                "kind": "wikipedia_redirect",
                "provider": "Wikipedia",
                "language": language,
                "url": f"https://www.wikidata.org/wiki/Special:GoToLinkedPage/{language}wiki/{wikidata.external_id}",
            }

        evidence = self.ordered_evidence(obj)
        if evidence:
            source = evidence[0].source
            return {
                "kind": "source",
                "provider": source.provider,
                "language": source.language,
                "url": source.url,
            }
        return None


class PortalArticleSerializer(serializers.ModelSerializer):
    assertion_count = serializers.IntegerField(source="assertions.count", read_only=True)
    source = SourceSerializer(read_only=True)

    class Meta:
        model = PortalArticle
        fields = (
            "id",
            "title",
            "url",
            "page_id",
            "revision_id",
            "position",
            "active",
            "assertion_count",
            "source",
            "metadata",
            "first_seen_at",
            "last_seen_at",
        )


class WikipediaPortalSerializer(serializers.ModelSerializer):
    subject_entity = EntitySerializer(read_only=True)
    scan_status_label = serializers.CharField(source="get_scan_status_display", read_only=True)

    class Meta:
        model = WikipediaPortal
        fields = (
            "id",
            "language",
            "title",
            "url",
            "page_id",
            "revision_id",
            "subject_entity",
            "scan_status",
            "scan_status_label",
            "article_count",
            "assertion_count",
            "last_scanned_at",
            "last_error",
            "metadata",
            "created_at",
            "updated_at",
        )


class AssertionReferenceSerializer(serializers.ModelSerializer):
    subject = EntitySerializer(read_only=True)
    value = serializers.CharField(source="display_value", read_only=True)
    temporal_extent = serializers.SerializerMethodField()

    class Meta:
        model = Assertion
        fields = ("id", "subject", "predicate", "value", "temporal_extent", "status", "knowledge_type", "confidence")

    def get_temporal_extent(self, obj):
        return obj.temporal_extent


class AssertionRelationSerializer(serializers.ModelSerializer):
    source_assertion = AssertionReferenceSerializer(read_only=True)
    target_assertion = AssertionReferenceSerializer(read_only=True)
    relation_type_label = serializers.CharField(source="get_relation_type_display", read_only=True)
    evidence_level_label = serializers.CharField(source="get_evidence_level_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    evidence = EvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = AssertionRelation
        fields = (
            "id",
            "source_assertion",
            "target_assertion",
            "relation_type",
            "relation_type_label",
            "evidence_level",
            "evidence_level_label",
            "summary",
            "mechanism",
            "confidence",
            "confidence_reason",
            "temporal_overlap_years",
            "spatial_distance_meters",
            "extraction_method",
            "algorithm_name",
            "algorithm_version",
            "status",
            "status_label",
            "metadata",
            "evidence",
            "created_at",
            "updated_at",
        )


def geometry_geojson(geometry):
    return json.loads(geometry.geojson) if geometry else None


class EnvironmentalDatasetSerializer(serializers.ModelSerializer):
    source = SourceSerializer(read_only=True)
    spatial_coverage = serializers.SerializerMethodField()
    data_kind_label = serializers.CharField(source="get_data_kind_display", read_only=True)

    class Meta:
        model = EnvironmentalDataset
        fields = (
            "id",
            "slug",
            "title",
            "provider",
            "source",
            "data_kind",
            "data_kind_label",
            "storage_kind",
            "asset_uri",
            "file_format",
            "variable_name",
            "unit",
            "spatial_coverage",
            "spatial_resolution_meters",
            "spatial_resolution_text",
            "time_start_year",
            "time_end_year",
            "reference_period_start_year",
            "reference_period_end_year",
            "metadata",
        )

    def get_spatial_coverage(self, obj):
        return geometry_geojson(obj.spatial_coverage)


class EnvironmentalEventSerializer(serializers.ModelSerializer):
    dataset = EnvironmentalDatasetSerializer(read_only=True)
    geometry = serializers.SerializerMethodField()
    map_point = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    distance_km = serializers.SerializerMethodField()
    evidence = EvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = EnvironmentalEvent
        fields = (
            "id",
            "external_id",
            "event_type",
            "event_type_label",
            "name",
            "description",
            "geometry",
            "map_point",
            "distance_km",
            "spatial_resolution_meters",
            "time_start_year",
            "time_end_year",
            "time_precision",
            "temporal_uncertainty_years",
            "status",
            "status_label",
            "confidence",
            "metadata",
            "dataset",
            "evidence",
        )

    def get_geometry(self, obj):
        return geometry_geojson(obj.geometry)

    def get_map_point(self, obj):
        if not obj.geometry:
            return None
        point = obj.geometry if obj.geometry.geom_type == "Point" else obj.geometry.centroid
        return {"latitude": point.y, "longitude": point.x}

    def get_name(self, obj):
        labels = obj.metadata.get("labels", {})
        for language in preferred_languages(self.context):
            if labels.get(language):
                return labels[language]
        return obj.name

    def get_description(self, obj):
        descriptions = obj.metadata.get("descriptions", {})
        for language in preferred_languages(self.context):
            if descriptions.get(language):
                return descriptions[language]
        return obj.description

    def get_distance_km(self, obj):
        distance = getattr(obj, "distance", None)
        return round(distance.km, 2) if distance is not None else None


class EnvironmentalObservationSerializer(serializers.ModelSerializer):
    dataset = EnvironmentalDatasetSerializer(read_only=True)
    geometry = serializers.SerializerMethodField()
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    spatial_scope_label = serializers.CharField(source="get_spatial_scope_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    evidence = EvidenceSerializer(many=True, read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True, default="")

    class Meta:
        model = EnvironmentalObservation
        fields = (
            "id",
            "external_id",
            "method",
            "method_label",
            "variable",
            "value",
            "value_min",
            "value_max",
            "value_text",
            "unit",
            "geometry",
            "spatial_scope",
            "spatial_scope_label",
            "spatial_resolution_meters",
            "time_start_year",
            "time_end_year",
            "time_precision",
            "temporal_uncertainty_years",
            "reference_period_start_year",
            "reference_period_end_year",
            "aggregation",
            "confidence",
            "status",
            "status_label",
            "asset_uri",
            "asset_window",
            "metadata",
            "event_name",
            "dataset",
            "evidence",
        )

    def get_geometry(self, obj):
        return geometry_geojson(obj.geometry)


class EnvironmentalRelationSerializer(serializers.ModelSerializer):
    environmental_event = EnvironmentalEventSerializer(read_only=True)
    historical_assertion = AssertionSerializer(read_only=True)
    relation_type_label = serializers.CharField(source="get_relation_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    evidence = EvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = EnvironmentalRelation
        fields = (
            "id",
            "environmental_event",
            "historical_assertion",
            "relation_type",
            "relation_type_label",
            "summary",
            "mechanism",
            "temporal_lag_years",
            "temporal_confidence",
            "spatial_confidence",
            "confidence",
            "status",
            "status_label",
            "uncertainty_note",
            "evidence",
        )


class ResearchRequestSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(write_only=True, min_value=-180, max_value=180)
    radius_km = serializers.IntegerField(min_value=1, max_value=1000, default=25)
    topics = serializers.ListField(child=serializers.CharField(max_length=120), required=False, default=list)
    languages = serializers.ListField(child=serializers.CharField(max_length=24), required=False, default=lambda: ["de", "en"])
    center = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ResearchRequest
        fields = (
            "id",
            "query",
            "latitude",
            "longitude",
            "center",
            "radius_km",
            "time_start_year",
            "time_end_year",
            "topics",
            "languages",
            "status",
            "trigger_count",
            "discovered_assertions",
            "error_message",
            "created_at",
            "last_requested_at",
            "completed_at",
        )
        read_only_fields = (
            "id",
            "status",
            "trigger_count",
            "discovered_assertions",
            "error_message",
            "created_at",
            "last_requested_at",
            "completed_at",
        )

    def validate(self, attrs):
        if attrs["time_start_year"] > attrs["time_end_year"]:
            raise serializers.ValidationError("Das Anfangsjahr muss vor dem Endjahr liegen.")
        return attrs

    def validate_languages(self, value):
        return validate_language_preferences(value)

    def create(self, validated_data):
        latitude = validated_data.pop("latitude")
        longitude = validated_data.pop("longitude")
        return ResearchRequest.objects.create(center=Point(longitude, latitude, srid=4326), **validated_data)

    def get_center(self, obj):
        return {"latitude": obj.center.y, "longitude": obj.center.x}


class ExplorationContextSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True, min_value=-90, max_value=90, required=False)
    longitude = serializers.FloatField(write_only=True, min_value=-180, max_value=180, required=False)
    center = serializers.SerializerMethodField(read_only=True)
    time_start_year = serializers.IntegerField(read_only=True)
    time_end_year = serializers.IntegerField(read_only=True)
    base_version = serializers.IntegerField(write_only=True, min_value=1, required=False)
    map_zoom = serializers.FloatField(min_value=1, max_value=20, required=False)
    radius_km = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    time_focus_year = serializers.IntegerField(min_value=-5_000_000_000, max_value=20_000, required=False)
    time_window_years = serializers.IntegerField(min_value=0, max_value=1_000_000_000, required=False)
    topics = serializers.ListField(child=serializers.CharField(max_length=120), required=False)
    perspectives = serializers.ListField(child=serializers.CharField(max_length=120), required=False)
    environmental_event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=EnvironmentalEvent.Type.choices),
        required=False,
    )
    languages = serializers.ListField(child=serializers.CharField(max_length=24), required=False)
    focus_entity = EntitySerializer(read_only=True)

    class Meta:
        model = ExplorationContext
        fields = (
            "id",
            "place_name",
            "latitude",
            "longitude",
            "center",
            "map_zoom",
            "time_focus_year",
            "time_window_years",
            "time_start_year",
            "time_end_year",
            "radius_km",
            "query",
            "query_mode",
            "anchor_mode",
            "focus_entity",
            "event_start_year",
            "event_end_year",
            "environmental_event_types",
            "environmental_place_name",
            "topics",
            "perspectives",
            "languages",
            "include_candidates",
            "version",
            "base_version",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "version", "created_at", "updated_at")

    def validate(self, attrs):
        latitude_supplied = "latitude" in attrs
        longitude_supplied = "longitude" in attrs
        if self.instance is None and latitude_supplied != longitude_supplied:
            raise serializers.ValidationError("Breiten- und Längengrad müssen gemeinsam angegeben werden.")
        attrs.pop("base_version", None)
        return attrs

    def validate_languages(self, value):
        return validate_language_preferences(value)

    def _set_center(self, instance, validated_data):
        latitude = validated_data.pop("latitude", None)
        longitude = validated_data.pop("longitude", None)
        if latitude is None and longitude is None:
            return
        current = instance.center if instance else Point(9.489, 53.836, srid=4326)
        instance.center = Point(
            longitude if longitude is not None else current.x,
            latitude if latitude is not None else current.y,
            srid=4326,
        )

    def create(self, validated_data):
        instance = ExplorationContext()
        self._set_center(instance, validated_data)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        moves_space_anchor = validated_data.get("anchor_mode") == ExplorationContext.AnchorMode.SPACE and (
            "latitude" in validated_data
            or "longitude" in validated_data
            or "place_name" in validated_data
        )
        self._set_center(instance, validated_data)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if moves_space_anchor:
            instance.focus_entity = None
            instance.event_start_year = None
            instance.event_end_year = None
            instance.environmental_event_types = []
            instance.environmental_place_name = ""
        instance.version += 1
        instance.save()
        return instance

    def get_center(self, obj):
        return {"latitude": obj.center.y, "longitude": obj.center.x}
