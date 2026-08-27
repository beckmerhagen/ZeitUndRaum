import hashlib
import re
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import Assertion, Coverage, Entity, Evidence, ExternalIdentifier, PlaceGeometry, ResearchRequest, Source
from .wikimedia import (
    linked_wikipedia_pages,
    nearby_wikipedia_pages,
    page_summary,
    wikipedia_history_section_page,
)
from .wikidata import ingest_wikidata_event_places, ingest_wikidata_time_world

YEAR_PATTERN = re.compile(r"(?<!\d)(?<!\d[.,])(\d{3,4})(?!\d)(?![.,]\d)")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
MEASUREMENT_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:(?:-|–|—|and|und|to|bis)\s*)?(?:\d{1,4}\s*)?"
    r"(?:m|km|cm|mm|m2|m²|km2|km²|ha|hectares?|hektar|feet|ft|meters?|metres?|meter|"
    r"t|tonnen?|tonnes?|tons?|kilotonnen?|kilotons?|megatons?|kg|kilograms?|kilogramm|g|grams?|gramm|"
    r"lbs?|pounds?|pfund|liters?|litres?|liter|l|percent|prozent|%|"
    r"watts?|kilowatts?|megawatts?|gigawatts?|kw|mw|gw|volts?|amp(?:ere)?s?|"
    r"°c|°f|degrees?|grad|km/h|mph)\b",
    re.IGNORECASE,
)
THREE_DIGIT_TIME_PREFIX_PATTERN = re.compile(
    r"(?:\bin|since|from|by|year|im\s+jahr|seit|ab|um|jahr)\s*$",
    re.IGNORECASE,
)
ERA_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:a\.?\s*d\.?|c\.?\s*e\.?|b\.?\s*c\.?\s*e?\.?|v\.\s*chr\.|n\.\s*chr\.)\b",
    re.IGNORECASE,
)
BCE_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:b\.?\s*c\.?\s*e?\.?|v\.\s*chr\.)\b",
    re.IGNORECASE,
)
NON_TEMPORAL_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"arten|tier(?:e|en)?|animals?|species|einwohner(?:innen)?|inhabitants?|residents?|"
    r"studierende|student(?:en|innen|s)?|pflanzenarten|plant\s+species|"
    r"räume|zimmer|rooms?|stufen|steps?|sitze|seats?|"
    r"beschäftigte|mitglieder|employees?|members?|haushalte|households?|"
    r"objekte|objects?|werke|works?|soldaten|soldiers?|personen|people|"
    r"besucher(?:innen)?|visitors?"
    r")\b",
    re.IGNORECASE,
)
COLLECTION_TITLE_PATTERN = re.compile(
    r"^(?:lists?\s+of|index\s+of|chronology\s+of|timeline\s+of|"
    r"listen?\s+(?:der|des|von)|chronologie\s+(?:der|des|von)|zeittafel\s+(?:der|des|von))\b",
    re.IGNORECASE,
)


def fingerprint(*parts):
    normalized = "|".join(str(part).strip().lower() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_candidate_years(sentence):
    years = []
    for match in YEAR_PATTERN.finditer(sentence):
        year = int(match.group(1))
        suffix = sentence[match.end() : match.end() + 32]
        prefix = sentence[max(0, match.start() - 24) : match.start()]
        if BCE_SUFFIX_PATTERN.search(suffix):
            year = -year
        if year > timezone.now().year or MEASUREMENT_SUFFIX_PATTERN.search(suffix):
            continue
        if NON_TEMPORAL_SUFFIX_PATTERN.search(suffix):
            continue
        digits = match.group(1)
        if len(digits) == 3 and not (
            THREE_DIGIT_TIME_PREFIX_PATTERN.search(prefix) or ERA_SUFFIX_PATTERN.search(suffix)
        ):
            continue
        if year not in years:
            years.append(year)
    return years


def contextual_candidate_years(sentence, title=""):
    """Use a sentence year first; replace a rejected quantity only from a unique title year."""
    sentence_years = extract_candidate_years(sentence)
    if sentence_years:
        return sentence_years
    if YEAR_PATTERN.search(sentence) is None:
        return []
    title_years = extract_candidate_years(title)
    return title_years[:1] if len(title_years) == 1 else []


def temporal_span(sentence, year):
    absolute_year = str(abs(year))
    decade_pattern = re.compile(
        rf"(?<!\d){re.escape(absolute_year)}(?:s|'s|er(?:[-\s]?jahre)?)\b",
        re.IGNORECASE,
    )
    if year >= 0 and decade_pattern.search(sentence):
        return year, year + 9, Assertion.Precision.DECADE, 9

    approximate_pattern = re.compile(
        rf"(?:circa|ca\.?|c\.?|around|about|approximately|etwa|ungefähr|um)\s+"
        rf"{re.escape(absolute_year)}\b",
        re.IGNORECASE,
    )
    uncertainty = 5 if approximate_pattern.search(sentence) else 0
    return year, year, Assertion.Precision.YEAR, uncertainty


def is_collection_title(title):
    return COLLECTION_TITLE_PATTERN.search((title or "").strip()) is not None


def wikipedia_pages(language, research):
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    common = {
        "action": "query",
        "format": "json",
        "prop": "extracts|coordinates|pageprops|info",
        "exlimit": "max",
        "explaintext": "1",
        "exintro": "1",
        "exsentences": "10",
        "inprop": "url",
    }
    if research.query:
        common.update(
            {
                "generator": "search",
                "gsrsearch": research.query,
                "gsrnamespace": "0",
                "gsrlimit": "8",
            }
        )
    else:
        common.update(
            {
                "generator": "geosearch",
                "ggsprimary": "all",
                "ggscoord": f"{research.center.y}|{research.center.x}",
        "ggsradius": str(max(10, min(research.radius_km * 1000, 10000))),
                "ggslimit": "12",
            }
        )

    response = requests.get(
        endpoint,
        params=common,
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    return sorted(pages.values(), key=lambda page: page.get("index", 999))


def title_matches_query(title, query):
    if not query:
        return True
    title_text = title.casefold()
    terms = [term for term in re.findall(r"\w+", query.casefold()) if len(term) >= 4]
    if not terms:
        return query.casefold() in title_text
    required = max(1, (len(terms) + 1) // 2)
    return sum(term in title_text for term in terms) >= required


def resolve_entity(page, language):
    qid = page.get("pageprops", {}).get("wikibase_item")
    provider = "wikidata" if qid else f"wikipedia-{language}"
    external_id = qid or str(page["pageid"])
    existing = ExternalIdentifier.objects.select_related("entity").filter(provider=provider, external_id=external_id).first()
    title = page.get("title", external_id)
    description = page.get("pageprops", {}).get("wikibase-shortdesc", "").strip()
    if existing:
        entity = existing.entity
        labels = {**entity.labels, language: title}
        descriptions = {**entity.descriptions, **({language: description} if description else {})}
        changed_fields = []
        if labels != entity.labels:
            entity.labels = labels
            changed_fields.append("labels")
        if descriptions != entity.descriptions:
            entity.descriptions = descriptions
            changed_fields.append("descriptions")
        if changed_fields:
            entity.save(update_fields=[*changed_fields, "updated_at"])
    else:
        entity = Entity.objects.create(
            canonical_name=title,
            kind=infer_entity_kind(title, description, bool(page.get("coordinates") or page.get("_coordinate"))),
            labels={language: title},
            descriptions={language: description} if description else {},
        )
        ExternalIdentifier.objects.create(
            entity=entity,
            provider=provider,
            external_id=external_id,
            url=page.get("fullurl", ""),
        )

    ExternalIdentifier.objects.get_or_create(
        entity=entity,
        provider=f"wikipedia-{language}",
        external_id=str(page["pageid"]),
        defaults={"url": page.get("fullurl", "")},
    )
    return entity


def infer_entity_kind(title, description, has_coordinates):
    text = f"{title} {description}".casefold()

    def contains_word(term):
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None

    if any(contains_word(term) for term in ("battle", "siege", "war", "schlacht", "belagerung", "krieg")):
        return Entity.Kind.EVENT
    if any(term in text for term in ("school", "academy", "university", "schule", "akademie", "universität")):
        return Entity.Kind.ORGANIZATION
    if any(term in text for term in ("stupa", "temple", "monastery", "museum", "church", "palace", "kloster", "kirche", "tempel")):
        return Entity.Kind.BUILDING
    return Entity.Kind.PLACE if has_coordinates else Entity.Kind.OTHER


def source_for_page(page, language):
    page_id = str(page.get("pageid", ""))
    thumbnail_url = page.get("thumbnail", {}).get("source", "")
    return Source.objects.update_or_create(
        provider=f"Wikipedia ({language})",
        record_id=page_id,
        url=page.get("fullurl", f"https://{language}.wikipedia.org/?curid={page_id}"),
        defaults={
            "title": page.get("title", page_id),
            "source_type": Source.Type.ENCYCLOPEDIA,
            "language": language,
            "license_name": "CC BY-SA – siehe Artikelseite",
            "license_url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de",
            "publisher": "Wikimedia Foundation / Wikipedia community",
            "retrieved_at": timezone.now(),
            "metadata": {
                "last_revision_id": page.get("lastrevid"),
                "thumbnail_url": thumbnail_url,
                "short_description": page.get("pageprops", {}).get("wikibase-shortdesc", ""),
            },
        },
    )


def ingest_nearby_page(page, language):
    coordinate_data = page.get("_coordinate")
    if not coordinate_data or is_collection_title(page.get("title", "")):
        return 0

    entity = resolve_entity(page, language)
    coordinate = Point(coordinate_data["lon"], coordinate_data["lat"], srid=4326)
    PlaceGeometry.objects.update_or_create(
        entity=entity,
        label="Wikipedia-Koordinate",
        defaults={
            "geometry": coordinate,
            "spatial_precision_meters": 100,
            "is_reconstruction": False,
        },
    )
    source, _ = source_for_page(page, language)
    summary = page_summary(page)
    assertion, was_created = Assertion.objects.get_or_create(
        fingerprint=fingerprint(entity.id, "nearby-place"),
        defaults={
            "subject": entity,
            "predicate": "nearby-place",
            "value_text": summary,
            "time_precision": Assertion.Precision.UNKNOWN,
            "location": coordinate,
            "spatial_precision_meters": 100,
            "status": Assertion.Status.CANDIDATE,
            "confidence": Decimal("0.68"),
            "extraction_method": "wikipedia-geosearch-v1",
        },
    )
    distance_km = Decimal(str(page.get("_distance_meters", 0))) / Decimal("1000")
    Evidence.objects.get_or_create(
        assertion=assertion,
        source=source,
        relation=Evidence.Relation.MENTIONS,
        defaults={
            "locator": f"Georeferenzierter Artikel, etwa {distance_km:.2f} km vom Suchzentrum",
            "excerpt": summary,
            "confidence": Decimal("0.68"),
        },
    )
    return int(was_created)


def ingest_page(
    page,
    language,
    research,
    *,
    max_assertions=18,
    extraction_method="wikipedia-sentence-year-v3",
    locator_prefix="Automatisch erkannter Satz zum Jahr",
    coordinate_confidence=Decimal("0.58"),
    portal_article=None,
):
    extract = page.get("extract", "").strip()
    if is_collection_title(page.get("title", "")):
        return 0

    if not extract:
        if portal_article is not None:
            source, _ = source_for_page(page, language)
            portal_article.source = source
            portal_article.page_id = page.get("pageid")
            portal_article.revision_id = page.get("lastrevid")
            portal_article.url = page.get("fullurl", portal_article.url)
            portal_article.metadata = {
                **portal_article.metadata,
                "content_status": "article_without_extract",
            }
            portal_article.save(
                update_fields=["source", "page_id", "revision_id", "url", "metadata", "last_seen_at"]
            )
        return 0

    entity = resolve_entity(page, language)
    source, _ = source_for_page(page, language)
    if portal_article is not None and portal_article.source_id != source.id:
        portal_article.source = source
        portal_article.page_id = page.get("pageid")
        portal_article.revision_id = page.get("lastrevid")
        portal_article.url = page.get("fullurl", portal_article.url)
        portal_article.save(update_fields=["source", "page_id", "revision_id", "url", "last_seen_at"])

    coordinate = None
    spatial_precision = None
    raw = page.get("_coordinate") or ((page.get("coordinates") or [None])[0])
    if raw:
        coordinate = Point(raw["lon"], raw["lat"], srid=4326)
        spatial_precision = 500

    stale_candidates = Assertion.objects.filter(
        subject=entity,
        extraction_method__in=("wikipedia-sentence-year-v1", "wikipedia-sentence-year-v2", "wikipedia-sentence-year-v3"),
        status=Assertion.Status.CANDIDATE,
    )
    for candidate in stale_candidates:
        if candidate.time_start_year not in contextual_candidate_years(candidate.value_text, entity.canonical_name):
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])

    if extraction_method == "wikipedia-history-section-v1":
        valid_history_sentences = {
            " ".join(sentence.split())[:1800]
            for sentence in SENTENCE_PATTERN.split(extract)
            if contextual_candidate_years(sentence, page.get("title", ""))
        }
        stale_history = (
            Assertion.objects.filter(
                subject=entity,
                extraction_method="wikipedia-history-section-v1",
                status=Assertion.Status.CANDIDATE,
                evidence__source__language=language,
            )
            .distinct()
        )
        for candidate in stale_history:
            if candidate.value_text not in valid_history_sentences:
                candidate.status = Assertion.Status.REJECTED
                candidate.save(update_fields=["status", "updated_at"])

    created = 0
    for sentence in SENTENCE_PATTERN.split(extract):
        years = contextual_candidate_years(sentence, page.get("title", ""))
        # Recherche baut den Wissensbestand eines Fundortes über alle Zeiten auf.
        # Der aktuelle Zeitfokus wird erst bei der Exploration als Sichtfilter angewandt.
        for year in years[:2]:
            clean_sentence = " ".join(sentence.split())[:1800]
            start_year, end_year, precision, uncertainty = temporal_span(clean_sentence, year)
            claim_fingerprint = fingerprint(entity.id, "historical-mention", clean_sentence, year)
            assertion, was_created = Assertion.objects.get_or_create(
                fingerprint=claim_fingerprint,
                defaults={
                    "subject": entity,
                    "predicate": "historical-mention",
                    "value_text": clean_sentence,
                    "time_start_year": start_year,
                    "time_end_year": end_year,
                    "time_precision": precision,
                    "temporal_uncertainty_years": uncertainty,
                    "location": coordinate,
                    "spatial_precision_meters": spatial_precision,
                    "status": Assertion.Status.CANDIDATE,
                    "confidence": coordinate_confidence if coordinate else Decimal("0.42"),
                    "extraction_method": extraction_method,
                },
            )
            Evidence.objects.get_or_create(
                assertion=assertion,
                source=source,
                relation=Evidence.Relation.MENTIONS,
                defaults={
                    "locator": f"{locator_prefix} {year}",
                    "excerpt": clean_sentence,
                    "confidence": assertion.confidence,
                },
            )
            if portal_article is not None:
                portal_article.assertions.add(assertion)
            created += int(was_created)
            if created >= max_assertions:
                return created
    return created


@transaction.atomic
def audit_imported_assertions():
    result = {"corrected": 0, "upgraded": 0, "rejected": 0}
    candidates = Assertion.objects.select_related("subject").filter(
        extraction_method__in=("wikipedia-sentence-year-v1", "wikipedia-sentence-year-v2", "wikipedia-sentence-year-v3"),
        status=Assertion.Status.CANDIDATE,
    )
    for candidate in candidates:
        if is_collection_title(candidate.subject.canonical_name):
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])
            result["rejected"] += 1
            continue

        years = contextual_candidate_years(candidate.value_text, candidate.subject.canonical_name)
        if not years:
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])
            result["rejected"] += 1
            continue

        current_year = candidate.time_start_year
        if current_year in years:
            year = current_year
        elif len(years) == 1:
            year = years[0]
        else:
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])
            result["rejected"] += 1
            continue

        start_year, end_year, precision, uncertainty = temporal_span(candidate.value_text, year)
        new_fingerprint = fingerprint(candidate.subject_id, "historical-mention", candidate.value_text, year)
        duplicate = Assertion.objects.filter(fingerprint=new_fingerprint).exclude(id=candidate.id).exists()
        if duplicate:
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])
            result["rejected"] += 1
            continue

        was_corrected = current_year != start_year
        candidate.time_start_year = start_year
        candidate.time_end_year = end_year
        candidate.time_precision = precision
        candidate.temporal_uncertainty_years = uncertainty
        candidate.extraction_method = "wikipedia-sentence-year-v3"
        candidate.fingerprint = new_fingerprint
        candidate.save(
            update_fields=[
                "time_start_year",
                "time_end_year",
                "time_precision",
                "temporal_uncertainty_years",
                "extraction_method",
                "fingerprint",
                "updated_at",
            ]
        )
        candidate.evidence.filter(relation=Evidence.Relation.MENTIONS).update(
            locator=f"Automatisch erkannter Satz zum Jahr {year}"
        )
        result["corrected" if was_corrected else "upgraded"] += 1

    nearby_collections = Assertion.objects.select_related("subject").filter(
        extraction_method="wikipedia-geosearch-v1",
        status=Assertion.Status.CANDIDATE,
    )
    for candidate in nearby_collections:
        if is_collection_title(candidate.subject.canonical_name):
            candidate.status = Assertion.Status.REJECTED
            candidate.save(update_fields=["status", "updated_at"])
            result["rejected"] += 1

    return result


def ingest_event_linked_page(page, language, research, event_entity):
    coordinate_data = page.get("_coordinate")
    extract = " ".join(page.get("extract", "").split())
    if not coordinate_data or not extract:
        return 0

    title = page.get("title", "")
    description = page.get("pageprops", {}).get("wikibase-shortdesc", "")
    kind = infer_entity_kind(title, description, True)
    years = [
        year
        for year in extract_candidate_years(extract)
        if research.time_start_year <= year <= research.time_end_year
    ]
    event_words = ("krieg", "war", "schlacht", "battle", "belagerung", "siege", "revolution", "aufstand")
    event_name_words = [word for word in re.findall(r"\w+", event_entity.canonical_name.casefold()) if len(word) >= 5]
    stems = [word[: max(5, len(word) - 2)] for word in event_name_words]
    text = f"{title} {description} {extract}".casefold()
    directly_named = any(stem in text for stem in stems)
    event_signal = kind == Entity.Kind.EVENT or any(word in text for word in event_words)
    if not directly_named and not (years and event_signal):
        return 0

    entity = resolve_entity(page, language)
    coordinate = Point(coordinate_data["lon"], coordinate_data["lat"], srid=4326)
    PlaceGeometry.objects.update_or_create(
        entity=entity,
        label="Wikipedia-Koordinate",
        defaults={
            "geometry": coordinate,
            "spatial_precision_meters": 500,
            "is_reconstruction": False,
        },
    )
    source, _ = source_for_page(page, language)
    if years:
        start_year = min(years)
        end_year = max(years)
        precision = Assertion.Precision.YEAR if start_year == end_year else Assertion.Precision.RANGE
        confidence = Decimal("0.60")
    else:
        start_year = research.time_start_year
        end_year = research.time_end_year
        precision = Assertion.Precision.RANGE
        confidence = Decimal("0.45")
    summary = page_summary(page)
    assertion, was_created = Assertion.objects.get_or_create(
        fingerprint=fingerprint(event_entity.id, entity.id, "related-to-event", start_year, end_year),
        defaults={
            "subject": entity,
            "object_entity": event_entity,
            "predicate": "related-to-event",
            "value_text": summary,
            "time_start_year": start_year,
            "time_end_year": end_year,
            "time_precision": precision,
            "location": coordinate,
            "spatial_precision_meters": 500,
            "status": Assertion.Status.CANDIDATE,
            "confidence": confidence,
            "extraction_method": "wikipedia-event-links-v1",
        },
    )
    Evidence.objects.get_or_create(
        assertion=assertion,
        source=source,
        relation=Evidence.Relation.MENTIONS,
        defaults={
            "locator": f"Vom Ereignisartikel verknüpfter, georeferenzierter Artikel ({language})",
            "excerpt": summary,
            "confidence": confidence,
        },
    )
    return int(was_created)


@shared_task(bind=True, autoretry_for=(requests.RequestException,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def run_research_request(self, request_id):
    research = ResearchRequest.objects.get(id=request_id)
    research.status = ResearchRequest.Status.RUNNING
    research.error_message = ""
    research.save(update_fields=["status", "error_message", "last_requested_at"])

    discovered = 0
    errors = []
    event_marker = next((topic for topic in research.topics if topic.startswith("__event__:")), None)
    event_qid = event_marker.split(":", 1)[1] if event_marker else ""
    wikidata_event_entity = None
    if event_qid:
        identifier = ExternalIdentifier.objects.select_related("entity").filter(
            provider="wikidata", external_id=event_qid
        ).first()
        wikidata_event_entity = identifier.entity if identifier else None
        if wikidata_event_entity:
            try:
                discovered += ingest_wikidata_event_places(research, wikidata_event_entity, event_qid)
            except requests.RequestException as error:
                errors.append(f"Wikidata-Ereignis: {error.__class__.__name__}")
    if "__time_world__" in research.topics:
        try:
            discovered += ingest_wikidata_time_world(research)
        except requests.RequestException as error:
            errors.append(f"Wikidata: {error.__class__.__name__}")
        languages = []
    else:
        languages = research.languages[:4]
    for language in languages:
        try:
            with transaction.atomic():
                event_entity = wikidata_event_entity
                event_page = None
                history_loaded = False
                if research.query:
                    for page in wikipedia_pages(language, research):
                        if title_matches_query(page.get("title", ""), research.query):
                            discovered += ingest_page(page, language, research)
                            if not history_loaded and page.get("coordinates"):
                                history_page = wikipedia_history_section_page(language, page)
                                if history_page:
                                    section = history_page.get("_history_section", "History")
                                    discovered += ingest_page(
                                        history_page,
                                        language,
                                        research,
                                        max_assertions=80,
                                        extraction_method="wikipedia-history-section-v1",
                                        locator_prefix=f"Wikipedia-Abschnitt ‚{section}‘, Satz zum Jahr",
                                        coordinate_confidence=Decimal("0.62"),
                                    )
                                    history_loaded = True
                            if event_marker and event_page is None:
                                event_page = page
                                event_entity = resolve_entity(page, language)
                if event_marker and event_entity and event_page:
                    for page in linked_wikipedia_pages(language, event_page.get("title", research.query)):
                        discovered += ingest_event_linked_page(page, language, research, event_entity)
                for page in nearby_wikipedia_pages(language, research.center, research.radius_km):
                    discovered += ingest_nearby_page(page, language)
                    discovered += ingest_page(page, language, research)
        except requests.RequestException as error:
            errors.append(f"Wikipedia ({language}): {error.__class__.__name__}")

    now = timezone.now()
    research.discovered_assertions = discovered
    research.completed_at = now
    research.error_message = "\n".join(errors)
    if errors and discovered:
        research.status = ResearchRequest.Status.PARTIAL
    elif errors:
        research.status = ResearchRequest.Status.FAILED
    else:
        research.status = ResearchRequest.Status.COMPLETE
    research.save(
        update_fields=["status", "discovered_assertions", "completed_at", "error_message", "last_requested_at"]
    )

    cell_key = f"{research.center.y:.2f}:{research.center.x:.2f}"
    topics = research.topics or ["allgemein"]
    for topic in topics:
        Coverage.objects.update_or_create(
            cell_key=cell_key,
            time_start_year=research.time_start_year,
            time_end_year=research.time_end_year,
            topic=topic,
            language=research.languages[0] if research.languages else "de",
            defaults={
                "score": min(Decimal("1.0"), Decimal(discovered) / Decimal("20")),
                "source_count": Source.objects.filter(
                    evidence__assertion__location__distance_lte=(research.center, D(km=research.radius_km))
                ).distinct().count(),
                "assertion_count": discovered,
                "last_researched_at": now,
            },
        )
    return {"request_id": request_id, "discovered_assertions": discovered, "errors": errors}


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def scan_wikipedia_portal_batch(self, languages=None, batch_size=1, article_limit=100):
    """Arbeitet den Portal-Katalog höflich in kleinen, fortsetzbaren Portionen ab."""

    from .models import WikipediaPortal
    from .portal_ingest import scan_portal
    from .portal_recovery import recover_interrupted_portal_scans

    languages = languages or ["de", "en", "fr"]
    recovery = None
    if (self.request.delivery_info or {}).get("redelivered"):
        recovery = recover_interrupted_portal_scans(languages=languages)
    results = []
    for _ in range(max(1, min(int(batch_size), 3))):
        with transaction.atomic():
            portal = (
                WikipediaPortal.objects.select_for_update(skip_locked=True)
                .filter(
                    language__in=languages,
                    scan_status__in=[WikipediaPortal.ScanStatus.PENDING, WikipediaPortal.ScanStatus.PARTIAL],
                )
                .order_by("last_scanned_at", "language", "title")
                .first()
            )
            if portal is None:
                break
            portal.scan_status = WikipediaPortal.ScanStatus.RUNNING
            portal.save(update_fields=["scan_status", "updated_at"])
        try:
            results.append(scan_portal(portal, article_limit=max(20, min(int(article_limit), 250))))
        except Exception as error:
            results.append(
                {
                    "portal": portal.title,
                    "language": portal.language,
                    "status": WikipediaPortal.ScanStatus.FAILED,
                    "error": f"{error.__class__.__name__}: {error}",
                }
            )

    remaining = WikipediaPortal.objects.filter(
        language__in=languages,
        scan_status__in=[WikipediaPortal.ScanStatus.PENDING, WikipediaPortal.ScanStatus.PARTIAL],
    ).exists()
    if not remaining:
        retryable_failed = WikipediaPortal.objects.filter(
            language__in=languages,
            scan_status=WikipediaPortal.ScanStatus.FAILED,
        ).annotate(scan_attempts=Count("scan_runs")).filter(scan_attempts__lt=3)
        retry_ids = list(retryable_failed.values_list("id", flat=True)[:100])
        if retry_ids:
            WikipediaPortal.objects.filter(id__in=retry_ids).update(
                scan_status=WikipediaPortal.ScanStatus.PENDING,
                last_error="",
            )
            remaining = True
    if remaining:
        scan_wikipedia_portal_batch.apply_async(
            kwargs={
                "languages": languages,
                "batch_size": batch_size,
                "article_limit": article_limit,
            },
            countdown=20,
        )
    return {"results": results, "remaining": remaining, "recovery": recovery}
