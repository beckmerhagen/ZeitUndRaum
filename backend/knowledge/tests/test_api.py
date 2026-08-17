from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from netCDF4 import Dataset

from knowledge.classification import classify_assertion
from knowledge.environment import nasa_power_series, owda_series
from knowledge.environmental_search import environmental_event_types_for_query, parse_environmental_query
from knowledge.models import (
    Assertion,
    AssertionRelation,
    Entity,
    EnvironmentalEvent,
    EnvironmentalRelation,
    Evidence,
    ExplorationContext,
    ExternalIdentifier,
    PortalArticle,
    ResearchRequest,
    Source,
    WikipediaPortal,
)
from knowledge.noaa_tsunami import import_noaa_tsunami_features
from knowledge.portal_ingest import discover_portals, scan_portal
from knowledge.serializers import AssertionSerializer
from knowledge.tasks import audit_imported_assertions, contextual_candidate_years, extract_candidate_years, ingest_nearby_page, ingest_page
from knowledge.wikidata import ingest_wikidata_event_places, ingest_wikidata_time_world
from knowledge.wikimedia import resolve_wikipedia_entity, wikipedia_history_section_page


@override_settings(NASA_POWER_ENABLED=False)
class ContextAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        entity = Entity.objects.create(canonical_name="Kremper Kirche St. Peter", kind=Entity.Kind.BUILDING)
        source = Source.objects.create(
            provider="Testarchiv",
            title="Kirchengeschichte",
            url="https://example.org/kirche",
            record_id="church-1",
            source_type=Source.Type.INSTITUTION,
            license_name="Testlizenz",
            retrieved_at=timezone.now(),
        )
        assertion = Assertion.objects.create(
            subject=entity,
            predicate="constructed",
            value_text="Die heutige Kirche wurde neu errichtet.",
            time_start_year=1828,
            time_end_year=1832,
            time_precision=Assertion.Precision.RANGE,
            location=Point(9.489, 53.836, srid=4326),
            spatial_precision_meters=500,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.9"),
            fingerprint="1" * 64,
        )
        Evidence.objects.create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.SUPPORTS,
            excerpt="Paraphrasierter Testbeleg",
            confidence=Decimal("0.9"),
        )

    def test_context_combines_space_and_time(self):
        response = self.client.get(
            "/api/v1/context/",
            {"lat": 53.836, "lon": 9.489, "year": 1830, "window_years": 1, "radius_km": 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["assertions"][0]["subject"]["canonical_name"], "Kremper Kirche St. Peter")
        self.assertEqual(response.data["assertions"][0]["status"], "verified")

    def test_context_excludes_wrong_time(self):
        response = self.client.get(
            "/api/v1/context/",
            {"lat": 53.836, "lon": 9.489, "year": 1700, "window_years": 5, "radius_km": 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_assertion_v2_exposes_exact_time_space_provenance_and_reason(self):
        entity = Entity.objects.create(canonical_name="Belagerung von Malta", kind=Entity.Kind.EVENT)
        source = Source.objects.create(
            provider="Wikidata",
            title="Belagerung von Malta",
            url="https://www.wikidata.org/wiki/Q58732",
            record_id="Q58732",
            license_name="CC0 1.0",
            retrieved_at=timezone.now(),
        )
        assertion = Assertion.objects.create(
            subject=entity,
            predicate="event-period",
            value_text="Die Große Belagerung dauerte vom 18. Mai bis 8. September 1565.",
            time_start_year=1565,
            time_start_month=5,
            time_start_day=18,
            time_end_year=1565,
            time_end_month=9,
            time_end_day=8,
            time_precision=Assertion.Precision.DAY,
            calendar_model=Assertion.CalendarModel.JULIAN,
            location=Point(14.5183, 35.8919, srid=4326),
            spatial_precision_meters=1000,
            status=Assertion.Status.VERIFIED,
            knowledge_type=Assertion.KnowledgeType.DOCUMENTED,
            confidence=Decimal("0.96"),
            confidence_reason="Beginn und Ende sind als strukturierte Wikidata-Zeitangaben überliefert.",
            extraction_method="wikidata-structured-v2",
            fingerprint="7" * 64,
        )
        Evidence.objects.create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.SUPPORTS,
            locator="Wikidata P580 und P582",
            excerpt="18 May 1565 – 8 September 1565",
            confidence=Decimal("0.96"),
        )

        assertion.refresh_from_db()
        serialized = AssertionSerializer(assertion).data

        self.assertEqual(assertion.temporal_scope, Assertion.TemporalScope.BOUNDED)
        self.assertEqual(assertion.spatial_scope, Assertion.SpatialScope.POINT)
        self.assertEqual(serialized["temporal_extent"]["start"], {"year": 1565, "month": 5, "day": 18})
        self.assertEqual(serialized["temporal_extent"]["end"], {"year": 1565, "month": 9, "day": 8})
        self.assertEqual(serialized["knowledge_type"], "documented")
        self.assertTrue(serialized["integrity"]["complete"])
        self.assertEqual(serialized["evidence"][0]["source"]["license_name"], "CC0 1.0")

    def test_wikidata_finding_links_directly_to_localized_wikipedia_article(self):
        entity = Entity.objects.create(canonical_name="Konklave 1565–1566", kind=Entity.Kind.EVENT)
        ExternalIdentifier.objects.create(
            entity=entity,
            provider="wikidata",
            external_id="Q4541682",
            url="https://www.wikidata.org/wiki/Q4541682",
        )
        assertion = Assertion.objects.create(
            subject=entity,
            predicate="point-in-time",
            value_text="Papstwahl",
            time_start_year=1565,
            time_end_year=1566,
            location=Point(12.48, 41.90, srid=4326),
            fingerprint="e" * 64,
        )

        serialized = AssertionSerializer(
            assertion,
            context={"preferred_languages": ["de", "en"]},
        ).data

        self.assertEqual(serialized["content_category"]["key"], "religious_event")
        self.assertEqual(serialized["preferred_link"]["kind"], "wikipedia_redirect")
        self.assertEqual(
            serialized["preferred_link"]["url"],
            "https://www.wikidata.org/wiki/Special:GoToLinkedPage/dewiki/Q4541682",
        )

    @patch("knowledge.wikimedia.wikipedia_request")
    def test_place_history_section_is_loaded_beyond_article_intro(self, mocked_request):
        mocked_request.side_effect = [
            {
                "parse": {
                    "sections": [
                        {"index": "1", "line": "Geography", "toclevel": 1},
                        {"index": "2", "line": "History", "toclevel": 1},
                    ]
                }
            },
            {
                "parse": {
                    "text": {
                        "*": "<h2>History</h2><p>The Great Siege took place in 1565.</p>"
                        "<p>The last British forces left in 1979.</p>"
                        "<p>Malta joined the European Union in 2004.</p>"
                        "<div class='mw-references-wrap'><ol class='references'>"
                        "<li>Historian, Some Book (2025).</li></ol></div>"
                    }
                }
            },
        ]
        history_page = wikipedia_history_section_page(
            "en",
            {"pageid": 1, "title": "Malta", "coordinates": [{"lat": 35.9, "lon": 14.5}]},
        )
        self.assertEqual(history_page["_history_section"], "History")
        self.assertIn("Great Siege took place in 1565", history_page["extract"])
        self.assertIn("last British forces left in 1979", history_page["extract"])
        self.assertIn("joined the European Union in 2004", history_page["extract"])
        self.assertNotIn("2025", history_page["extract"])

    def test_malta_milestones_are_exact_dated_and_officially_sourced(self):
        call_command("seed_malta_milestones")
        milestones = Assertion.objects.filter(extraction_method="curated-official-source-v1").order_by(
            "time_start_year"
        )
        self.assertEqual(list(milestones.values_list("time_start_year", flat=True)), [1565, 1979, 2004])
        self.assertEqual(
            list(milestones.values_list("time_start_month", "time_start_day")),
            [(5, 18), (3, 31), (5, 1)],
        )
        self.assertTrue(all(item.status == Assertion.Status.VERIFIED for item in milestones))
        self.assertTrue(all(item.knowledge_type == Assertion.KnowledgeType.DOCUMENTED for item in milestones))
        self.assertTrue(all(item.evidence.exists() for item in milestones))
        eu_accession = milestones.get(time_start_year=2004)
        self.assertEqual(AssertionSerializer(eu_accession).data["value"], "Malta trat am 1. Mai 2004 der Europäischen Union bei.")

        context = ExplorationContext.objects.create(
            place_name="Malta",
            center=Point(14.4477, 35.8880, srid=4326),
            radius_km=1,
            time_focus_year=2004,
            languages=["de", "en"],
        )
        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/timeline/")
        self.assertEqual(response.status_code, 200)
        milestone_years = {
            moment["year"]
            for moment in response.data["moments"]
            if any(
                assertion["extraction_method"] == "curated-official-source-v1"
                for assertion in moment["assertions"]
            )
        }
        self.assertEqual(milestone_years, {1565, 1979, 2004})

    @patch("knowledge.portal_ingest.wikipedia_article_pages")
    @patch("knowledge.portal_ingest.wikipedia_portal_links")
    def test_portal_scan_preserves_discovery_path_and_article_evidence(self, mocked_links, mocked_pages):
        malta = Entity.objects.create(
            canonical_name="Malta",
            kind=Entity.Kind.POLITY,
            labels={"de": "Malta", "en": "Malta"},
        )
        portal = WikipediaPortal.objects.create(
            language="de",
            title="Portal:Malta",
            url="https://de.wikipedia.org/wiki/Portal:Malta",
            page_id=99,
            subject_entity=malta,
        )
        mocked_links.return_value = {
            "links": [
                {
                    "title": "Große Belagerung Maltas",
                    "fullurl": "https://de.wikipedia.org/wiki/Gro%C3%9Fe_Belagerung_Maltas",
                }
            ],
            "revision_id": 12345,
            "complete": True,
            "continuation": {},
        }
        mocked_pages.return_value = [
            {
                "pageid": 123,
                "lastrevid": 456,
                "title": "Große Belagerung Maltas",
                "fullurl": "https://de.wikipedia.org/wiki/Gro%C3%9Fe_Belagerung_Maltas",
                "extract": "Die Große Belagerung Maltas begann 1565.",
                "pageprops": {"wikibase-shortdesc": "Belagerung Maltas"},
            }
        ]

        result = scan_portal(portal, article_limit=50)

        portal.refresh_from_db()
        self.assertEqual(result["new_assertions"], 1)
        self.assertEqual(portal.scan_status, WikipediaPortal.ScanStatus.COMPLETE)
        self.assertEqual(portal.revision_id, 12345)
        self.assertEqual(portal.article_count, 1)
        self.assertEqual(portal.assertion_count, 1)
        article = PortalArticle.objects.get(portal=portal)
        assertion = article.assertions.get()
        evidence = assertion.evidence.get()
        self.assertEqual(assertion.time_start_year, 1565)
        self.assertEqual(evidence.source.url, article.url)
        self.assertIn("Portal:Malta", evidence.locator)

        context = ExplorationContext.objects.create(
            place_name="Malta",
            center=Point(14.4477, 35.8880, srid=4326),
            radius_km=1,
            time_focus_year=1565,
            languages=["de", "en"],
        )
        timeline = self.client.get(f"/api/v1/exploration-contexts/{context.id}/timeline/")
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.data["count"], 1)
        trail = timeline.data["moments"][0]["assertions"][0]["discovered_via_portals"][0]
        self.assertEqual(trail["portal_title"], "Portal:Malta")
        self.assertEqual(trail["role"], "discovery_only")

        catalog = self.client.get("/api/v1/wikipedia-portals/", {"language": "de", "q": "Malta"})
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.data["results"][0]["title"], "Portal:Malta")

    @patch("knowledge.portal_ingest.wikipedia_portal_pages")
    def test_portal_catalog_refresh_preserves_scan_continuation(self, mocked_portal_pages):
        portal = WikipediaPortal.objects.create(
            language="de",
            title="Portal:Malta",
            url="https://de.wikipedia.org/wiki/Portal:Malta",
            scan_status=WikipediaPortal.ScanStatus.PARTIAL,
            metadata={"continuation": {"plcontinue": "next"}},
        )
        mocked_portal_pages.return_value = [
            {
                "title": "Portal:Malta",
                "fullurl": "https://de.wikipedia.org/wiki/Portal:Malta",
            }
        ]

        discover_portals(["de"])

        portal.refresh_from_db()
        self.assertEqual(portal.metadata["continuation"], {"plcontinue": "next"})
        self.assertEqual(portal.metadata["discovery"], "wikipedia-curated-portal-directory-v1")
        self.assertEqual(portal.scan_status, WikipediaPortal.ScanStatus.PARTIAL)

    def test_assertion_relations_keep_coincidence_separate_from_causality(self):
        source_assertion = Assertion.objects.get(fingerprint="1" * 64)
        target_entity = Entity.objects.create(canonical_name="Zeitgleiches Ereignis", kind=Entity.Kind.EVENT)
        target_assertion = Assertion.objects.create(
            subject=target_entity,
            predicate="historical-event",
            value_text="Ein anderes Ereignis fand zur selben Zeit statt.",
            time_start_year=1830,
            time_end_year=1830,
            time_precision=Assertion.Precision.YEAR,
            location=Point(9.50, 53.84, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            confidence_reason="Jahresangabe ist durch die Testquelle belegt.",
            fingerprint="8" * 64,
        )
        relation = AssertionRelation.objects.create(
            source_assertion=source_assertion,
            target_assertion=target_assertion,
            relation_type=AssertionRelation.Type.CONTEMPORARY_WITH,
            evidence_level=AssertionRelation.EvidenceLevel.COINCIDENCE,
            summary="Die Zeiträume überschneiden sich; eine Ursache wird nicht behauptet.",
            confidence=Decimal("1.0"),
            confidence_reason="Die gespeicherten Zeitintervalle überlappen sich im Jahr 1830.",
            temporal_overlap_years=1,
            extraction_method="temporal-overlap-v1",
            status=Assertion.Status.VERIFIED,
        )

        invalid = AssertionRelation(
            source_assertion=source_assertion,
            target_assertion=target_assertion,
            relation_type=AssertionRelation.Type.CAUSES,
            evidence_level=AssertionRelation.EvidenceLevel.COINCIDENCE,
            summary="Unzulässige Kausalitätsbehauptung.",
            confidence=Decimal("0.4"),
            confidence_reason="Nur zeitliche Nähe.",
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

        response = self.client.get(
            "/api/v1/assertion-relations/",
            {"assertion": str(source_assertion.id), "lang": "de"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["relations"][0]["id"], str(relation.id))
        self.assertEqual(response.data["relations"][0]["evidence_level"], "coincidence")
        self.assertEqual(response.data["relations"][0]["relation_type"], "contemporary_with")

    def test_algorithmic_similarity_requires_named_versioned_method(self):
        source_assertion = Assertion.objects.get(fingerprint="1" * 64)
        target_entity = Entity.objects.create(canonical_name="Vergleichsobjekt", kind=Entity.Kind.BUILDING)
        target_assertion = Assertion.objects.create(
            subject=target_entity,
            predicate="constructed",
            value_text="Ein vergleichbares Bauwerk wurde errichtet.",
            time_start_year=1830,
            time_end_year=1830,
            location=Point(9.6, 53.9, srid=4326),
            confidence=Decimal("0.7"),
            confidence_reason="Automatisch aus einem datierten Satz extrahiert.",
            fingerprint="6" * 64,
        )
        relation = AssertionRelation(
            source_assertion=source_assertion,
            target_assertion=target_assertion,
            relation_type=AssertionRelation.Type.SIMILAR_TO,
            evidence_level=AssertionRelation.EvidenceLevel.ALGORITHMIC_SIMILARITY,
            summary="Automatisch erkannte strukturelle Ähnlichkeit.",
            confidence=Decimal("0.62"),
            confidence_reason="Ähnliche Begriffe und Zeitmuster.",
            extraction_method="embedding-comparison",
        )
        with self.assertRaises(ValidationError):
            relation.full_clean()

        relation.algorithm_name = "Tripanion similarity"
        relation.algorithm_version = "1.0"
        relation.full_clean()

    def test_living_conditions_keep_prior_event_for_current_environmental_effect(self):
        context = ExplorationContext.objects.create(
            place_name="Marne",
            center=Point(9.0086, 53.9536, srid=4326),
            time_focus_year=1816,
            time_window_years=0,
            radius_km=25,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/living-conditions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["event_count"], 1)
        self.assertEqual(response.data["events"][0]["name"], "Ausbruch des Tambora")
        self.assertEqual(response.data["observation_count"], 1)
        self.assertEqual(response.data["observations"][0]["method"], "reconstruction")
        self.assertEqual(response.data["observations"][0]["spatial_scope"], "global")
        self.assertEqual(response.data["observations"][0]["unit"], "Tg S")
        self.assertEqual(response.data["relation_count"], 0)
        self.assertEqual(response.data["reference_place"]["name"], "Marne")
        self.assertEqual(response.data["reference_place"]["center"]["latitude"], 53.9536)
        self.assertEqual(response.data["time_range"]["start_year"], 1816)
        self.assertEqual(response.data["time_range"]["end_year"], 1816)
        self.assertIn("nicht belegt", response.data["assessment"])
        self.assertEqual(
            {dataset["slug"] for dataset in response.data["datasets"]},
            {"smithsonian-gvp-eruptions", "evolv2k-v2"},
        )
        self.assertIn("NetCDF", response.data["storage_policy"])

    def test_living_conditions_only_show_historical_consequence_via_relation(self):
        tambora = EnvironmentalEvent.objects.get(external_id="264040:1815")
        local_subject = Entity.objects.create(canonical_name="Marne im Jahr 1816", kind=Entity.Kind.PLACE)
        local_assertion = Assertion.objects.create(
            subject=local_subject,
            predicate="documented-environmental-impact",
            value_text="Ein zeitgenössischer Bericht beschreibt eine lokale Auswirkung.",
            time_start_year=1816,
            time_end_year=1816,
            time_precision=Assertion.Precision.YEAR,
            location=Point(9.0086, 53.9536, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="9" * 64,
        )
        EnvironmentalRelation.objects.create(
            environmental_event=tambora,
            historical_assertion=local_assertion,
            relation_type=EnvironmentalRelation.Type.POSSIBLE,
            summary="Ein möglicher Zusammenhang, der noch weiterer lokaler Belege bedarf.",
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.6"),
            uncertainty_note="Zeitliche Nähe allein beweist keine Ursache.",
        )
        context = ExplorationContext.objects.create(
            place_name="Marne",
            center=Point(9.0086, 53.9536, srid=4326),
            time_focus_year=1816,
            time_window_years=0,
            radius_km=25,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/living-conditions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["relation_count"], 1)
        self.assertEqual(response.data["relations"][0]["relation_type"], "possible")
        self.assertIn("keine Ursache", response.data["relations"][0]["uncertainty_note"])

    @patch("knowledge.views.build_climate_series")
    def test_living_conditions_exposes_graph_ready_climate_series(self, build_climate_series):
        build_climate_series.return_value = (
            [
                {
                    "id": "owda-pdsi",
                    "title": "Sommerliche Feuchte und Dürre",
                    "unit": "PDSI",
                    "method": "reconstruction",
                    "focus_year": 1816,
                    "focus_point": {"year": 1816, "value": -0.716},
                    "points": [
                        {"year": 1815, "value": 0.25},
                        {"year": 1816, "value": -0.716},
                    ],
                }
            ],
            [],
        )
        context = ExplorationContext.objects.create(
            place_name="Marne",
            center=Point(9.0086, 53.9536, srid=4326),
            time_focus_year=1816,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/living-conditions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["climate_series_count"], 1)
        self.assertEqual(response.data["climate_series"][0]["focus_point"]["year"], 1816)
        self.assertEqual(response.data["climate_series"][0]["points"][1]["value"], -0.716)

    def test_owda_reader_extracts_nearest_grid_cell_and_focus_year(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "owda.nc"
            years = list(range(1766, 1867))
            with Dataset(path, "w") as dataset:
                dataset.createDimension("lon", 2)
                dataset.createDimension("lat", 2)
                dataset.createDimension("time", len(years))
                dataset.createVariable("lon", "f8", ("lon",))[:] = [9.25, 10.25]
                dataset.createVariable("lat", "f8", ("lat",))[:] = [53.75, 54.25]
                dataset.createVariable("time", "i4", ("time",))[:] = years
                pdsi = dataset.createVariable("pdsi", "f8", ("lon", "lat", "time"), fill_value=9.969e36)
                pdsi[:, :, :] = 0.25
                pdsi[0, 0, years.index(1816)] = -0.716
            context = ExplorationContext(
                place_name="Marne",
                center=Point(9.0086, 53.9536, srid=4326),
                time_focus_year=1816,
                time_window_years=0,
            )

            with self.settings(OWDA_NETCDF_PATH=str(path)):
                series = owda_series(context)
                context.time_focus_year = 2025
                outside_coverage = owda_series(context)
                context.time_focus_year = 1816
                context.languages = ["fr", "en"]
                french_series = owda_series(context)

        self.assertEqual(series["focus_point"], {"year": 1816, "value": -0.716})
        self.assertEqual(series["location_label"], "Rasterpunkt 53.75° N, 9.25° E")
        self.assertEqual(len(series["points"]), 101)
        self.assertIsNone(outside_coverage)
        self.assertEqual(french_series["title"], "Humidité estivale et sécheresse")
        self.assertEqual(french_series["focus_interpretation"], "dans la plage des fluctuations ordinaires")

    @override_settings(NASA_POWER_ENABLED=True)
    @patch("knowledge.environment.nasa_power_monthly")
    def test_nasa_power_builds_global_monthly_table_and_annual_trends(self, monthly):
        temperatures = {}
        precipitation = {}
        for year in range(1981, 2026):
            for month in range(1, 13):
                temperatures[f"{year:04d}{month:02d}"] = 10 + month / 2 + (year - 1981) / 100
                precipitation[f"{year:04d}{month:02d}"] = 1.0
            temperatures[f"{year:04d}13"] = 13.5 + (year - 1981) / 100
        monthly.return_value = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [85.324, 27.717, 1269.39]},
            "properties": {"parameter": {"T2M": temperatures, "PRECTOTCORR": precipitation}},
        }
        context = ExplorationContext(
            place_name="Kathmandu",
            center=Point(85.324, 27.717, srid=4326),
            time_focus_year=2020,
            languages=["de", "en"],
        )

        series = nasa_power_series(context)

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["id"], "nasa-power-temperature")
        self.assertEqual(series[1]["id"], "nasa-power-precipitation")
        table = series[0]["monthly_table"]
        self.assertEqual(table["period"], "1991–2020")
        self.assertEqual(len(table["rows"]), 12)
        self.assertEqual(table["rows"][0]["precipitation"], 31)
        self.assertEqual(series[0]["focus_point"]["year"], 2020)
        self.assertIn("NASA POWER", series[0]["source"]["provider"])

    @patch("knowledge.views.run_research_request.delay")
    def test_research_request_is_queued(self, delay):
        response = self.client.post(
            "/api/v1/research/",
            {
                "query": "Krempe",
                "latitude": 53.836,
                "longitude": 9.489,
                "radius_km": 25,
                "time_start_year": 1800,
                "time_end_year": 1850,
                "topics": ["Kirchen"],
                "languages": ["de", "en"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "queued")
        delay.assert_called_once()

    def test_research_rejects_inverted_period(self):
        response = self.client.post(
            "/api/v1/research/",
            {
                "query": "Krempe",
                "latitude": 53.836,
                "longitude": 9.489,
                "time_start_year": 1900,
                "time_end_year": 1800,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_exploration_context_normalizes_browser_languages(self):
        response = self.client.post(
            "/api/v1/exploration-contexts/",
            {"languages": ["fr-FR", "de", "fr"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["languages"], ["fr", "de"])

    def test_exploration_context_rejects_unsafe_language_codes(self):
        response = self.client.post(
            "/api/v1/exploration-contexts/",
            {"languages": ["de.example.org"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_wikipedia_summary_prefers_context_language(self):
        entity = Entity.objects.create(
            canonical_name="Beispielort",
            kind=Entity.Kind.PLACE,
            labels={"de": "Beispielort", "en": "Example place"},
        )
        assertion = Assertion.objects.create(
            subject=entity,
            predicate="nearby-place",
            value_text="Deutsche Zusammenfassung.",
            location=Point(9.49, 53.84, srid=4326),
            status=Assertion.Status.CANDIDATE,
            extraction_method="wikipedia-geosearch-v1",
            fingerprint="b" * 64,
        )
        for language, text in (("de", "Deutsche Zusammenfassung."), ("en", "English summary.")):
            source = Source.objects.create(
                provider=f"Wikipedia ({language})",
                title="Example",
                url=f"https://{language}.wikipedia.org/wiki/Example",
                record_id=f"example-{language}",
                language=language,
                retrieved_at=timezone.now(),
            )
            Evidence.objects.create(
                assertion=assertion,
                source=source,
                relation=Evidence.Relation.MENTIONS,
                excerpt=text,
            )

        serialized = AssertionSerializer(
            assertion,
            context={"preferred_languages": ["en", "de"]},
        ).data
        self.assertEqual(serialized["subject"]["canonical_name"], "Example place")
        self.assertEqual(serialized["value"], "English summary.")
        self.assertEqual(serialized["evidence"][0]["source"]["language"], "en")

    def test_exploration_context_is_persisted_and_resolves_results(self):
        created = self.client.post(
            "/api/v1/exploration-contexts/",
            {
                "place_name": "Krempe",
                "latitude": 53.836,
                "longitude": 9.489,
                "time_focus_year": 1830,
                "time_window_years": 1,
                "radius_km": 5,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        context_id = created.data["id"]

        results = self.client.get(f"/api/v1/exploration-contexts/{context_id}/results/")
        self.assertEqual(results.status_code, 200)
        self.assertEqual(results.data["count"], 1)
        self.assertEqual(results.data["exploration_context"]["time_focus_year"], 1830)

    def test_partial_context_update_keeps_time_while_moving(self):
        context = ExplorationContext.objects.create(
            place_name="Krempe",
            center=Point(9.489, 53.836, srid=4326),
            time_focus_year=1648,
            time_window_years=0,
        )
        response = self.client.patch(
            f"/api/v1/exploration-contexts/{context.id}/",
            {
                "place_name": "Münster",
                "latitude": 51.9607,
                "longitude": 7.6261,
                "base_version": context.version,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["place_name"], "Münster")
        self.assertEqual(response.data["time_focus_year"], 1648)
        self.assertEqual(response.data["time_window_years"], 0)
        self.assertEqual(response.data["version"], 2)

    def test_stale_context_update_is_rejected_without_overwriting(self):
        context = ExplorationContext.objects.create(time_focus_year=1648, version=3)
        response = self.client.patch(
            f"/api/v1/exploration-contexts/{context.id}/",
            {"time_focus_year": 1814, "base_version": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        context.refresh_from_db()
        self.assertEqual(context.time_focus_year, 1648)

    @patch("knowledge.views.resolve_wikipedia_entity")
    def test_place_query_moves_space_but_keeps_time(self, resolve_place):
        resolve_place.return_value = {
            "kind": "place",
            "title": "Boudha Stupa",
            "language": "en",
            "latitude": 27.72138889,
            "longitude": 85.36194444,
            "page": {},
        }
        context = ExplorationContext.objects.create(time_focus_year=1648, time_window_years=0)
        response = self.client.post(
            f"/api/v1/exploration-contexts/{context.id}/resolve/",
            {"query": "Boudha Stupa", "base_version": context.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_as"], "place")
        self.assertEqual(response.data["exploration_context"]["place_name"], "Boudha Stupa")
        self.assertEqual(response.data["exploration_context"]["time_focus_year"], 1648)
        self.assertEqual(response.data["exploration_context"]["query_mode"], "place")
        self.assertAlmostEqual(response.data["exploration_context"]["center"]["latitude"], 27.72138889)

    @patch("knowledge.wikimedia.wikidata_entity", return_value={})
    @patch("knowledge.wikimedia.wikipedia_request")
    def test_ambiguous_place_uses_current_center_to_select_georeferenced_candidate(
        self, wikipedia_request, wikidata_entity
    ):
        wikipedia_request.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "index": 1,
                        "title": "Marne",
                        "extract": "Marne steht für verschiedene Orte und einen Fluss.",
                        "pageprops": {"disambiguation": "", "wikibase_item": "Q1"},
                    },
                    "2": {
                        "pageid": 2,
                        "index": 2,
                        "title": "Marne (Fluss)",
                        "coordinates": [{"lat": 48.8164, "lon": 2.4108}],
                        "extract": "Die Marne ist ein Fluss in Frankreich.",
                        "pageprops": {"wikibase_item": "Q2"},
                    },
                    "3": {
                        "pageid": 3,
                        "index": 4,
                        "title": "Marne (Holstein)",
                        "coordinates": [{"lat": 53.9536, "lon": 9.0086}],
                        "extract": "Marne ist eine Stadt im Kreis Dithmarschen.",
                        "pageprops": {"wikibase_item": "Q3"},
                        "fullurl": "https://de.wikipedia.org/wiki/Marne_(Holstein)",
                    },
                }
            }
        }

        result = resolve_wikipedia_entity(
            "Marne",
            ["de"],
            reference_center=Point(9.489, 53.836, srid=4326),
        )

        self.assertEqual(result["kind"], "place")
        self.assertEqual(result["title"], "Marne (Holstein)")
        self.assertAlmostEqual(result["latitude"], 53.9536)

    @patch("knowledge.wikimedia.wikidata_entity")
    @patch("knowledge.wikimedia.wikipedia_request")
    def test_german_region_with_war_in_article_stays_a_place(
        self, wikipedia_request, wikidata_entity
    ):
        wikipedia_request.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "index": 1,
                        "title": "Dithmarschen",
                        "extract": (
                            "Dithmarschen ist eine Region in Schleswig-Holstein. "
                            "Dithmarschen war zeitweise eine Bauernrepublik und wurde in Kriegen umkämpft."
                        ),
                        "pageprops": {"wikibase_item": "Q619"},
                        "fullurl": "https://de.wikipedia.org/wiki/Dithmarschen",
                    }
                }
            }
        }
        wikidata_entity.return_value = {
            "descriptions": {"de": {"value": "Region in Schleswig-Holstein"}},
            "claims": {
                "P625": [
                    {
                        "rank": "normal",
                        "mainsnak": {
                            "datavalue": {
                                "value": {"latitude": 54.1253278, "longitude": 8.9988389}
                            }
                        },
                    }
                ]
            },
        }

        result = resolve_wikipedia_entity("Dithmarschen", ["de"])

        self.assertEqual(result["kind"], "place")
        self.assertEqual(result["title"], "Dithmarschen")
        self.assertAlmostEqual(result["latitude"], 54.1253278)
        self.assertAlmostEqual(result["longitude"], 8.9988389)
        self.assertEqual(result["coordinate_source"], "wikidata")

    @patch("knowledge.wikimedia.wikidata_entity", return_value={})
    @patch("knowledge.wikimedia.wikipedia_request")
    def test_german_event_title_is_still_recognized(self, wikipedia_request, wikidata_entity):
        wikipedia_request.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "index": 1,
                        "title": "Dreißigjähriger Krieg",
                        "extract": "Der Konflikt dauerte von 1618 bis 1648.",
                        "pageprops": {"wikibase_item": "Q2487"},
                    }
                }
            }
        }

        result = resolve_wikipedia_entity("Dreißigjähriger Krieg", ["de"])

        self.assertEqual(result["kind"], "event")

    @patch("knowledge.views.resolve_wikipedia_entity", return_value=None)
    def test_non_geographic_query_stays_a_topic(self, resolve_place):
        context = ExplorationContext.objects.create(time_focus_year=1789)
        original_center = context.center.clone()
        response = self.client.post(
            f"/api/v1/exploration-contexts/{context.id}/resolve/",
            {"query": "Französische Revolution", "base_version": context.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_as"], "topic")
        self.assertEqual(response.data["exploration_context"]["query_mode"], "topic")
        context.refresh_from_db()
        self.assertEqual((context.center.x, context.center.y), (original_center.x, original_center.y))

    def test_environmental_category_recognition_does_not_capture_concrete_events(self):
        self.assertEqual(environmental_event_types_for_query("Erdbeben"), ["earthquake"])
        self.assertEqual(environmental_event_types_for_query("Erdbeben von Lissabon"), [])
        self.assertEqual(
            set(environmental_event_types_for_query("séismes et éruptions volcaniques")),
            {"earthquake", "volcano"},
        )
        self.assertEqual(
            set(environmental_event_types_for_query("Naturkatastrophen")),
            set(EnvironmentalEvent.Type.values) - {EnvironmentalEvent.Type.OTHER},
        )

    def test_environmental_query_separates_event_type_and_place(self):
        self.assertEqual(
            parse_environmental_query("Hamburg Sturmflut"),
            {"event_types": [EnvironmentalEvent.Type.STORM_SURGE], "place_query": "hamburg"},
        )
        self.assertEqual(
            parse_environmental_query("Sturmflut Dithmarschen"),
            {"event_types": [EnvironmentalEvent.Type.STORM_SURGE], "place_query": "dithmarschen"},
        )
        self.assertEqual(
            parse_environmental_query("Tsunami Thailand"),
            {"event_types": [EnvironmentalEvent.Type.TSUNAMI], "place_query": "thailand"},
        )

    @patch("knowledge.views.resolve_wikipedia_entity")
    def test_natural_event_and_place_query_sets_spatial_filter_without_time_filter(self, resolve_entity):
        resolve_entity.return_value = {
            "kind": "place",
            "title": "Hamburg",
            "language": "de",
            "latitude": 53.5503,
            "longitude": 9.9920,
            "page": {},
        }
        context = ExplorationContext.objects.create(
            place_name="Agra",
            center=Point(78.0081, 27.1767, srid=4326),
            time_focus_year=1565,
            time_window_years=0,
        )

        response = self.client.post(
            f"/api/v1/exploration-contexts/{context.id}/resolve/",
            {"query": "Hamburg Sturmflut", "base_version": context.version},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_as"], "environment")
        self.assertEqual(response.data["environment"]["event_types"], ["storm_surge"])
        self.assertEqual(response.data["environment"]["scope"], "place")
        result = response.data["exploration_context"]
        self.assertEqual(result["environmental_place_name"], "Hamburg")
        self.assertEqual(result["place_name"], "Hamburg")
        self.assertEqual(result["time_focus_year"], 1565)
        self.assertEqual(result["radius_km"], 50)
        self.assertAlmostEqual(result["center"]["latitude"], 53.5503)
        resolve_entity.assert_called_once()

    def test_noaa_tsunami_observations_are_grouped_by_event_and_affected_country(self):
        features = [
            {
                "geometry": {"type": "Point", "coordinates": [98.42, 7.83]},
                "properties": {
                    "ID": 9070,
                    "TSEVENT_ID": 2439,
                    "YEAR": 2004,
                    "DATE_STRING": "2004/12/26",
                    "LOCATION_NAME": "PHUKET",
                    "COUNTRY": "THAILAND",
                    "RUNUP_HT": 1.11,
                    "TYPE_MEASUREMENT": "Tide-gauge measurement",
                    "TSEVENT_URL": "https://example.org/tsunami/2439",
                },
            },
            {
                "geometry": {"type": "Point", "coordinates": [98.34, 7.82]},
                "properties": {
                    "ID": 9072,
                    "TSEVENT_ID": 2439,
                    "YEAR": 2004,
                    "DATE_STRING": "2004/12/26",
                    "LOCATION_NAME": "CHALONG",
                    "COUNTRY": "THAILAND",
                    "RUNUP_HT": 4.0,
                    "TYPE_MEASUREMENT": "Post-tsunami survey",
                    "TSEVENT_URL": "https://example.org/tsunami/2439",
                },
            },
        ]

        result = import_noaa_tsunami_features(features)

        self.assertEqual(result["created"], 1)
        event = EnvironmentalEvent.objects.get(event_type=EnvironmentalEvent.Type.TSUNAMI)
        self.assertEqual(event.time_start_year, 2004)
        self.assertEqual(event.metadata["country"], "THAILAND")
        self.assertEqual(event.metadata["observation_count"], 2)
        self.assertEqual(event.metadata["maximum_water_height_m"], 4.0)
        self.assertEqual(event.geometry.geom_type, "MultiPoint")

    @patch("knowledge.views.resolve_wikipedia_entity")
    def test_natural_event_category_is_global_and_has_no_time_filter(self, resolve_entity):
        context = ExplorationContext.objects.create(
            place_name="Agra",
            center=Point(78.0081, 27.1767, srid=4326),
            time_focus_year=1565,
            time_window_years=0,
        )

        response = self.client.post(
            f"/api/v1/exploration-contexts/{context.id}/resolve/",
            {"query": "Vulkanausbrüche", "base_version": context.version},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_as"], "environment")
        self.assertEqual(response.data["environment"]["event_types"], ["volcano"])
        self.assertEqual(response.data["exploration_context"]["anchor_mode"], "environment")
        self.assertEqual(response.data["exploration_context"]["query_mode"], "environment")
        self.assertEqual(response.data["exploration_context"]["place_name"], "Agra")
        self.assertEqual(response.data["exploration_context"]["time_focus_year"], 1565)
        resolve_entity.assert_not_called()

    def test_environmental_event_search_ignores_context_place_and_time(self):
        earthquake = EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.EARTHQUAKE,
            name="Testbeben im Pazifik",
            description="Ein räumlich entferntes Testereignis.",
            geometry=Point(-155.0, 19.0, srid=4326),
            time_start_year=2024,
            time_end_year=2024,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.9"),
        )
        EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.STORM_SURGE,
            name="Nicht gewählte Sturmflut",
            geometry=Point(8.5, 54.0, srid=4326),
            time_start_year=1962,
            time_end_year=1962,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.9"),
        )
        context = ExplorationContext.objects.create(
            place_name="Agra",
            center=Point(78.0081, 27.1767, srid=4326),
            time_focus_year=1565,
            environmental_event_types=[EnvironmentalEvent.Type.EARTHQUAKE],
            query="Erdbeben",
            query_mode=ExplorationContext.QueryMode.ENVIRONMENT,
            anchor_mode=ExplorationContext.AnchorMode.ENVIRONMENT,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/environmental-events/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["events"][0]["id"], str(earthquake.id))
        self.assertEqual(response.data["events"][0]["map_point"], {"latitude": 19.0, "longitude": -155.0})
        self.assertEqual(response.data["selection"]["scope"], "global")
        self.assertEqual(response.data["selection"]["time_scope"], "all")
        self.assertFalse(response.data["selection"]["place_filter_applied"])
        self.assertFalse(response.data["selection"]["time_filter_applied"])
        self.assertEqual(response.data["time_extent"], {"start_year": 2024, "end_year": 2024})
        self.assertEqual(response.data["exploration_context"]["query_mode"], "environment")

    def test_environmental_event_search_filters_by_resolved_place_but_not_time(self):
        near = EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.STORM_SURGE,
            name="Hamburger Sturmflut",
            geometry=Point(9.9920, 53.5503, srid=4326),
            time_start_year=1962,
            time_end_year=1962,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.9"),
        )
        EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.STORM_SURGE,
            name="Entfernte Sturmflut",
            geometry=Point(4.9, 52.4, srid=4326),
            time_start_year=1953,
            time_end_year=1953,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.9"),
        )
        context = ExplorationContext.objects.create(
            place_name="Hamburg",
            environmental_place_name="Hamburg",
            center=Point(9.9920, 53.5503, srid=4326),
            radius_km=25,
            time_focus_year=1565,
            environmental_event_types=[EnvironmentalEvent.Type.STORM_SURGE],
            query="Hamburg Sturmflut",
            query_mode=ExplorationContext.QueryMode.ENVIRONMENT,
            anchor_mode=ExplorationContext.AnchorMode.ENVIRONMENT,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/environmental-events/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["events"][0]["id"], str(near.id))
        self.assertEqual(response.data["selection"]["scope"], "place")
        self.assertTrue(response.data["selection"]["place_filter_applied"])
        self.assertEqual(response.data["selection"]["place_filter_method"], "radius")
        self.assertFalse(response.data["selection"]["time_filter_applied"])
        self.assertEqual(response.data["selection"]["reference_place"]["name"], "Hamburg")

    def test_country_environmental_search_prefers_explicit_source_assignment(self):
        thailand = EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.TSUNAMI,
            name="Tsunami-Beobachtungen · Thailand (2004)",
            geometry=Point(98.4, 7.8, srid=4326),
            time_start_year=2004,
            time_end_year=2004,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.95"),
            metadata={"country": "THAILAND"},
        )
        EnvironmentalEvent.objects.create(
            event_type=EnvironmentalEvent.Type.TSUNAMI,
            name="Tsunami-Beobachtungen · Myanmar (2004)",
            geometry=Point(98.1, 13.0, srid=4326),
            time_start_year=2004,
            time_end_year=2004,
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.95"),
            metadata={"country": "MYANMAR"},
        )
        context = ExplorationContext.objects.create(
            place_name="Thailand",
            environmental_place_name="Thailand",
            center=Point(101.03, 15.35, srid=4326),
            radius_km=1000,
            environmental_event_types=[EnvironmentalEvent.Type.TSUNAMI],
            query="Tsunami Thailand",
            query_mode=ExplorationContext.QueryMode.ENVIRONMENT,
            anchor_mode=ExplorationContext.AnchorMode.ENVIRONMENT,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/environmental-events/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["events"][0]["id"], str(thailand.id))
        self.assertEqual(response.data["selection"]["place_filter_method"], "source_country")

    @patch("knowledge.views.resolve_wikipedia_entity")
    def test_event_query_keeps_reference_place_and_sets_event_period(self, resolve_entity):
        resolve_entity.return_value = {
            "kind": "event",
            "title": "Dreißigjähriger Krieg",
            "language": "de",
            "qid": "Q2487",
            "description": "Militärischer Konflikt 1618 bis 1648 in Europa",
            "extract": "Der Dreißigjährige Krieg dauerte von 1618 bis 1648.",
            "start_year": 1618,
            "end_year": 1648,
            "page_url": "https://de.wikipedia.org/wiki/Dreißigjähriger_Krieg",
            "image_url": "",
            "page": {"pageid": 1054},
        }
        context = ExplorationContext.objects.create(
            place_name="Krempe",
            center=Point(9.489, 53.836, srid=4326),
            time_focus_year=2026,
        )
        response = self.client.post(
            f"/api/v1/exploration-contexts/{context.id}/resolve/",
            {"query": "30-jähriger Krieg", "base_version": context.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_as"], "event")
        result = response.data["exploration_context"]
        self.assertEqual(result["anchor_mode"], "event")
        self.assertEqual(result["query_mode"], "event")
        self.assertEqual(result["place_name"], "Krempe")
        self.assertEqual(result["event_start_year"], 1618)
        self.assertEqual(result["event_end_year"], 1648)
        self.assertEqual(result["time_focus_year"], 1633)
        self.assertAlmostEqual(result["center"]["longitude"], 9.489)

        dossier = self.client.get(f"/api/v1/exploration-contexts/{context.id}/event-dossier/")
        self.assertEqual(dossier.status_code, 200)
        self.assertEqual(dossier.data["event"]["canonical_name"], "Dreißigjähriger Krieg")
        self.assertEqual(dossier.data["start_year"], 1618)
        self.assertEqual(dossier.data["end_year"], 1648)

    def test_geosearch_page_becomes_timeless_nearby_assertion(self):
        page = {
            "pageid": 5530804,
            "title": "Boudha Stupa",
            "fullurl": "https://en.wikipedia.org/wiki/Boudha_Stupa",
            "pageprops": {
                "wikibase_item": "Q889902",
                "wikibase-shortdesc": "Buddhist stupa in Boudha, Kathmandu, Nepal",
            },
            "thumbnail": {"source": "https://upload.wikimedia.org/example.jpg"},
            "_coordinate": {"lat": 27.72138889, "lon": 85.36194444},
            "_distance_meters": 0,
        }
        self.assertEqual(ingest_nearby_page(page, "en"), 1)
        assertion = Assertion.objects.get(predicate="nearby-place")
        self.assertIsNone(assertion.time_start_year)
        self.assertEqual(assertion.subject.canonical_name, "Boudha Stupa")
        self.assertEqual(assertion.location.y, 27.72138889)
        self.assertEqual(assertion.evidence.first().source.metadata["thumbnail_url"], "https://upload.wikimedia.org/example.jpg")

    def test_place_timeline_ignores_current_focus_year(self):
        earlier = Entity.objects.create(canonical_name="Früher Bau", kind=Entity.Kind.BUILDING)
        Assertion.objects.create(
            subject=earlier,
            predicate="first-mentioned",
            value_text="Der Bau wurde erstmals erwähnt.",
            time_start_year=1239,
            time_end_year=1239,
            time_precision=Assertion.Precision.YEAR,
            location=Point(9.489, 53.836, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="b" * 64,
        )
        context = ExplorationContext.objects.create(
            place_name="Krempe",
            center=Point(9.489, 53.836, srid=4326),
            time_focus_year=2026,
            time_window_years=0,
            radius_km=5,
            anchor_mode=ExplorationContext.AnchorMode.SPACE,
        )
        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/timeline/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["moment_count"], 2)
        self.assertEqual(response.data["moments"][0]["year"], 1828)
        self.assertEqual(response.data["moments"][0]["end_year"], 1832)
        self.assertEqual(response.data["moments"][1]["year"], 1239)

    def test_place_timeline_keeps_large_exploration_radius_local(self):
        agra = Entity.objects.create(canonical_name="Rotes Fort", kind=Entity.Kind.BUILDING)
        kathmandu = Entity.objects.create(canonical_name="Budhanilkantha", kind=Entity.Kind.PLACE)
        Assertion.objects.create(
            subject=agra,
            predicate="constructed",
            value_text="Bauwerk in Agra.",
            time_start_year=1565,
            time_end_year=1565,
            time_precision=Assertion.Precision.YEAR,
            location=Point(78.0081, 27.1767, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="g" * 64,
        )
        Assertion.objects.create(
            subject=kathmandu,
            predicate="population",
            value_text="Aussage aus dem Kathmandutal.",
            time_start_year=2021,
            time_end_year=2021,
            time_precision=Assertion.Precision.YEAR,
            location=Point(85.37, 27.77, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="h" * 64,
        )
        context = ExplorationContext.objects.create(
            place_name="Agra",
            center=Point(78.0081, 27.1767, srid=4326),
            time_focus_year=1565,
            time_window_years=50,
            radius_km=1000,
            anchor_mode=ExplorationContext.AnchorMode.SPACE,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/timeline/")

        self.assertEqual(response.status_code, 200)
        subjects = {
            assertion["subject"]["canonical_name"]
            for moment in response.data["moments"]
            for assertion in moment["assertions"]
        }
        self.assertIn("Rotes Fort", subjects)
        self.assertNotIn("Budhanilkantha", subjects)
        self.assertEqual(response.data["scope"]["local_radius_km"], 25)
        self.assertEqual(response.data["scope"]["exploration_radius_km"], 1000)
        self.assertEqual(response.data["reference_place"]["name"], "Agra")

    def test_moving_space_anchor_clears_previous_event_focus(self):
        event = Entity.objects.create(canonical_name="Früheres Ereignis", kind=Entity.Kind.EVENT)
        context = ExplorationContext.objects.create(
            place_name="Rom",
            center=Point(12.48, 41.90, srid=4326),
            anchor_mode=ExplorationContext.AnchorMode.EVENT,
            query_mode=ExplorationContext.QueryMode.EVENT,
            focus_entity=event,
            event_start_year=1565,
            event_end_year=1566,
        )

        response = self.client.patch(
            f"/api/v1/exploration-contexts/{context.id}/",
            {
                "place_name": "Agra",
                "latitude": 27.1767,
                "longitude": 78.0081,
                "anchor_mode": "space",
                "query_mode": "place",
                "base_version": context.version,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["focus_entity"])
        self.assertIsNone(response.data["event_start_year"])
        self.assertIsNone(response.data["event_end_year"])

    def test_place_timeline_with_event_focus_excludes_unrelated_entries(self):
        event = Entity.objects.create(canonical_name="Dreißigjähriger Krieg", kind=Entity.Kind.EVENT)
        related = Entity.objects.create(canonical_name="Belagerung im Dreißigjährigen Krieg", kind=Entity.Kind.EVENT)
        Assertion.objects.create(
            subject=related,
            object_entity=event,
            predicate="part-of-event",
            value_text="Ein belegter örtlicher Bezug zum Dreißigjährigen Krieg.",
            time_start_year=1625,
            time_end_year=1625,
            time_precision=Assertion.Precision.YEAR,
            location=Point(9.489, 53.836, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="c" * 64,
        )
        context = ExplorationContext.objects.create(
            place_name="Krempe",
            center=Point(9.489, 53.836, srid=4326),
            time_focus_year=1633,
            time_window_years=15,
            radius_km=1000,
            anchor_mode=ExplorationContext.AnchorMode.SPACE,
            query_mode=ExplorationContext.QueryMode.EVENT,
            focus_entity=event,
            event_start_year=1618,
            event_end_year=1648,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/timeline/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["filter"], {"type": "event", "name": "Dreißigjähriger Krieg"})
        self.assertEqual(response.data["moment_count"], 1)
        self.assertEqual(response.data["moments"][0]["year"], 1625)
        self.assertNotIn(1828, [moment["year"] for moment in response.data["moments"]])

    def test_time_world_finds_other_places_outside_radius(self):
        remote = Entity.objects.create(canonical_name="Ereignis in New York", kind=Entity.Kind.EVENT)
        Assertion.objects.create(
            subject=remote,
            predicate="historical-event",
            value_text="Ein zeitgleiches Ereignis an einem anderen Ort.",
            time_start_year=1830,
            time_end_year=1830,
            time_precision=Assertion.Precision.YEAR,
            location=Point(-74.006, 40.7128, srid=4326),
            status=Assertion.Status.VERIFIED,
            confidence=Decimal("0.8"),
            fingerprint="b" * 64,
        )
        context = ExplorationContext.objects.create(
            center=Point(9.489, 53.836, srid=4326),
            time_focus_year=1830,
            time_window_years=0,
            radius_km=5,
            anchor_mode=ExplorationContext.AnchorMode.TIME,
        )
        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/time-world/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        scopes = {scope["key"]: scope for scope in response.data["scopes"]}
        self.assertEqual(scopes["local"]["count"], 1)
        self.assertEqual(scopes["global"]["count"], 1)
        self.assertEqual(response.data["result_semantics"], "dated_assertions_not_causal_events")
        self.assertEqual(response.data["selection"]["start_year"], 1830)
        self.assertEqual(response.data["selection"]["end_year"], 1830)
        self.assertEqual(response.data["selection"]["reference_place"]["radius_km"], 5)
        self.assertEqual(
            {category["key"] for category in response.data["categories"]},
            {"building", "event"},
        )

    def test_time_world_exposes_conflict_cluster_as_question_not_causal_claim(self):
        for index, (name, longitude) in enumerate(
            (("Belagerung A", 14.5), ("Schlacht B", 18.0)),
            start=1,
        ):
            entity = Entity.objects.create(canonical_name=name, kind=Entity.Kind.EVENT)
            Assertion.objects.create(
                subject=entity,
                predicate="historical-event",
                value_text=f"{name} war ein bewaffneter Konflikt.",
                time_start_year=1565,
                time_end_year=1565,
                location=Point(longitude, 40.0, srid=4326),
                confidence=Decimal("0.7"),
                fingerprint=str(index + 2) * 64,
            )
        context = ExplorationContext.objects.create(
            place_name="Rom",
            center=Point(12.48, 41.90, srid=4326),
            time_focus_year=1565,
            time_window_years=50,
            radius_km=1000,
            anchor_mode=ExplorationContext.AnchorMode.TIME,
        )

        response = self.client.get(f"/api/v1/exploration-contexts/{context.id}/time-world/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["selection"]["start_year"], 1515)
        self.assertEqual(response.data["selection"]["end_year"], 1615)
        self.assertEqual(response.data["selection"]["window_years"], 100)
        patterns = {pattern["key"]: pattern for pattern in response.data["patterns"]}
        self.assertEqual(patterns["conflict_cluster"]["evidence_level"], "algorithmic_similarity")
        self.assertEqual(patterns["religious_conflict_question"]["evidence_level"], "coincidence")
        self.assertEqual(
            patterns["religious_conflict_question"]["limitation"],
            "participants_and_motives_not_verified",
        )

    def test_german_verb_war_does_not_turn_a_region_into_a_conflict(self):
        region = Entity.objects.create(
            canonical_name="Dithmarschen",
            kind=Entity.Kind.PLACE,
            labels={"de": "Dithmarschen"},
            descriptions={"de": "Region in Schleswig-Holstein"},
        )
        assertion = Assertion.objects.create(
            subject=region,
            predicate="population",
            value_text="Dithmarschen war im Jahr 2022 eine Region mit rund 135000 Einwohnern.",
            time_start_year=2022,
            time_end_year=2022,
            location=Point(8.9988, 54.1253, srid=4326),
            fingerprint="f" * 64,
        )

        self.assertEqual(classify_assertion(assertion)["key"], "place")

    def test_time_pivot_keeps_place_and_changes_anchor(self):
        context = ExplorationContext.objects.create(
            place_name="Boudha Stupa",
            center=Point(85.36194444, 27.72138889, srid=4326),
            time_focus_year=2026,
        )
        response = self.client.patch(
            f"/api/v1/exploration-contexts/{context.id}/",
            {"time_focus_year": 1768, "anchor_mode": "time", "base_version": context.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["anchor_mode"], "time")
        self.assertEqual(response.data["place_name"], "Boudha Stupa")
        self.assertEqual(response.data["time_focus_year"], 1768)
        self.assertAlmostEqual(response.data["center"]["longitude"], 85.36194444)

    def test_research_imports_dates_outside_current_time_window(self):
        research = ResearchRequest.objects.create(
            query="Boudha Stupa",
            center=Point(85.36194444, 27.72138889, srid=4326),
            radius_km=25,
            time_start_year=2026,
            time_end_year=2026,
        )
        page = {
            "pageid": 5530804,
            "title": "Boudha Stupa",
            "fullurl": "https://en.wikipedia.org/wiki/Boudha_Stupa",
            "extract": "The monument was restored in 1768 after an earlier phase.",
            "pageprops": {"wikibase_item": "Q889902"},
            "coordinates": [{"lat": 27.72138889, "lon": 85.36194444}],
        }
        self.assertEqual(ingest_page(page, "en", research), 1)
        assertion = Assertion.objects.get(subject__canonical_name="Boudha Stupa", time_start_year=1768)
        self.assertEqual(assertion.time_end_year, 1768)

    def test_measurements_and_grouped_numbers_are_not_dates(self):
        sentence = "The site covers 246 hectares, contains 2,460,000 m2 and lies between 1300 and 2700 m."
        self.assertEqual(extract_candidate_years(sentence), [])
        self.assertEqual(extract_candidate_years("It became a World Heritage Site in 1979."), [1979])
        beirut = "Die Bundesanstalt schätzte die Sprengkraft auf 1100 Tonnen TNT-Äquivalent."
        self.assertEqual(extract_candidate_years(beirut), [])
        self.assertEqual(contextual_candidate_years(beirut, "Explosionskatastrophe in Beirut 2020"), [2020])
        self.assertEqual(
            contextual_candidate_years("Die Explosion verwüstete den Hafen.", "Explosionskatastrophe in Beirut 2020"),
            [],
        )

    def test_decades_counts_and_eras_are_distinguished(self):
        self.assertEqual(extract_candidate_years("From the mid-1960s, the garden was neglected."), [1960])
        self.assertEqual(extract_candidate_years("Der Zoo beherbergt über 900 Tiere in 127 Arten."), [])
        self.assertEqual(extract_candidate_years("The sanctuary was built in 127 AD."), [127])
        self.assertEqual(extract_candidate_years("The settlement existed in 500 BCE."), [-500])

    def test_collection_page_does_not_create_list_level_history(self):
        research = ResearchRequest.objects.create(
            query="List of stupas in Nepal",
            center=Point(85.32, 27.71, srid=4326),
            radius_km=25,
            time_start_year=1600,
            time_end_year=1700,
        )
        page = {
            "pageid": 123,
            "title": "List of stupas in Nepal",
            "fullurl": "https://en.wikipedia.org/wiki/List_of_stupas_in_Nepal",
            "extract": "Kaathe Swayambhu, a replica of Swayambhunath, was built in 1650.",
            "pageprops": {"wikibase_item": "Q123"},
            "_coordinate": {"lat": 27.71, "lon": 85.32},
        }
        self.assertEqual(ingest_nearby_page(page, "en"), 0)
        self.assertEqual(ingest_page(page, "en", research), 0)
        self.assertFalse(Assertion.objects.filter(time_start_year=1650).exists())

    def test_audit_corrects_decade_and_rejects_count_and_collection(self):
        garden = Entity.objects.create(canonical_name="Garden of Dreams", kind=Entity.Kind.PLACE)
        zoo = Entity.objects.create(canonical_name="Central Zoo", kind=Entity.Kind.PLACE)
        collection = Entity.objects.create(canonical_name="List of stupas in Nepal", kind=Entity.Kind.OTHER)
        garden_assertion = Assertion.objects.create(
            subject=garden,
            predicate="historical-mention",
            value_text="From the mid-1960s, the garden was neglected.",
            time_start_year=-1960,
            time_end_year=-1960,
            time_precision=Assertion.Precision.YEAR,
            status=Assertion.Status.CANDIDATE,
            extraction_method="wikipedia-sentence-year-v1",
            fingerprint="d" * 64,
        )
        count_assertion = Assertion.objects.create(
            subject=zoo,
            predicate="historical-mention",
            value_text="Der Zoo beherbergt über 900 Tiere in 127 Arten.",
            time_start_year=127,
            time_end_year=127,
            time_precision=Assertion.Precision.YEAR,
            status=Assertion.Status.CANDIDATE,
            extraction_method="wikipedia-sentence-year-v1",
            fingerprint="e" * 64,
        )
        list_assertion = Assertion.objects.create(
            subject=collection,
            predicate="historical-mention",
            value_text="Kaathe Swayambhu, a replica of Swayambhunath, was built in 1650.",
            time_start_year=1650,
            time_end_year=1650,
            time_precision=Assertion.Precision.YEAR,
            status=Assertion.Status.CANDIDATE,
            extraction_method="wikipedia-sentence-year-v1",
            fingerprint="f" * 64,
        )

        result = audit_imported_assertions()

        garden_assertion.refresh_from_db()
        count_assertion.refresh_from_db()
        list_assertion.refresh_from_db()
        self.assertEqual(result, {"corrected": 1, "upgraded": 0, "rejected": 2})
        self.assertEqual(garden_assertion.time_start_year, 1960)
        self.assertEqual(garden_assertion.time_end_year, 1969)
        self.assertEqual(garden_assertion.time_precision, Assertion.Precision.DECADE)
        self.assertEqual(count_assertion.status, Assertion.Status.REJECTED)
        self.assertEqual(list_assertion.status, Assertion.Status.REJECTED)

    def test_audit_corrects_tnt_quantity_to_unique_event_title_year(self):
        beirut = Entity.objects.create(canonical_name="Explosionskatastrophe in Beirut 2020", kind=Entity.Kind.EVENT)
        source = Source.objects.create(
            provider="Wikipedia (de)",
            title="Explosionskatastrophe in Beirut 2020",
            url="https://de.wikipedia.org/wiki/Explosionskatastrophe_in_Beirut_2020",
            retrieved_at=timezone.now(),
        )
        assertion = Assertion.objects.create(
            subject=beirut,
            predicate="historical-mention",
            value_text="Die deutsche Bundesanstalt schätzte die Sprengkraft auf 1100 Tonnen TNT-Äquivalent.",
            time_start_year=1100,
            time_end_year=1100,
            time_precision=Assertion.Precision.YEAR,
            status=Assertion.Status.CANDIDATE,
            extraction_method="wikipedia-sentence-year-v2",
            fingerprint="a" * 64,
        )
        evidence = Evidence.objects.create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.MENTIONS,
            locator="Automatisch erkannter Satz zum Jahr 1100",
        )

        result = audit_imported_assertions()

        assertion.refresh_from_db()
        evidence.refresh_from_db()
        self.assertEqual(result, {"corrected": 1, "upgraded": 0, "rejected": 0})
        self.assertEqual(assertion.time_start_year, 2020)
        self.assertEqual(assertion.time_end_year, 2020)
        self.assertEqual(assertion.extraction_method, "wikipedia-sentence-year-v3")
        self.assertEqual(evidence.locator, "Automatisch erkannter Satz zum Jahr 2020")

    @patch("knowledge.wikidata.requests.get")
    def test_time_world_imports_georeferenced_wikidata_items(self, get):
        response = get.return_value
        response.json.return_value = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "https://www.wikidata.org/entity/Q123"},
                        "itemLabel": {"value": "Zeitgleiches Bauwerk"},
                        "itemDescription": {"value": "Bauwerk in London"},
                        "coord": {"value": "Point(-0.1276 51.5072)"},
                        "date": {"value": "1768-01-01T00:00:00Z"},
                        "dateProp": {"value": "http://www.wikidata.org/prop/direct/P571"},
                        "instance": {"value": "http://www.wikidata.org/entity/Q41176"},
                        "sitelinks": {"value": "12"},
                    }
                ]
            }
        }
        research = ResearchRequest.objects.create(
            center=Point(85.36194444, 27.72138889, srid=4326),
            radius_km=25,
            time_start_year=1768,
            time_end_year=1768,
            topics=["__time_world__"],
        )
        self.assertEqual(ingest_wikidata_time_world(research), 1)
        assertion = Assertion.objects.get(extraction_method="wikidata-time-world-v1")
        self.assertEqual(assertion.time_start_year, 1768)
        self.assertEqual(assertion.subject.canonical_name, "Zeitgleiches Bauwerk")
        self.assertEqual(assertion.evidence.first().source.license_name, "CC0 1.0")
        self.assertEqual(assertion.metadata["wikidata_instance_ids"], ["Q41176"])
        self.assertEqual(AssertionSerializer(assertion).data["content_category"]["key"], "building")

    @patch("knowledge.wikidata.requests.get")
    def test_event_import_links_georeferenced_subevents(self, get):
        get.return_value.json.return_value = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q7510280"},
                        "itemLabel": {"value": "Belagerung von Nürnberg"},
                        "itemDescription": {"value": "Belagerung im Dreißigjährigen Krieg"},
                        "coord": {"value": "Point(11.08333333 49.45)"},
                        "date": {"value": "1632-01-01T00:00:00Z"},
                    }
                ]
            }
        }
        event = Entity.objects.create(canonical_name="Dreißigjähriger Krieg", kind=Entity.Kind.EVENT)
        research = ResearchRequest.objects.create(
            query="Dreißigjähriger Krieg",
            center=Point(9.489, 53.836, srid=4326),
            time_start_year=1618,
            time_end_year=1648,
        )
        self.assertEqual(ingest_wikidata_event_places(research, event, "Q2487"), 1)
        assertion = Assertion.objects.get(extraction_method="wikidata-event-places-v1")
        self.assertEqual(assertion.object_entity, event)
        self.assertEqual(assertion.time_start_year, 1632)
        self.assertEqual(assertion.subject.canonical_name, "Belagerung von Nürnberg")
