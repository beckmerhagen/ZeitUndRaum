"""Zeitbezogene Weltrecherche über den offiziellen Wikidata-SPARQL-Endpunkt."""

import hashlib
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone

from .models import Assertion, Entity, Evidence, ExternalIdentifier, Source
from .wikimedia import wikipedia_page_url

WKT_POINT_PATTERN = re.compile(r"^Point\(([-+\d.eE]+)\s+([-+\d.eE]+)\)$")
DATE_PREDICATES = {
    "P585": "point-in-time",
    "P580": "started",
    "P571": "inception",
}
WIKIPEDIA_LANGUAGES = ("de", "en", "fr")


def fetch_wikipedia_sitelinks(qids, languages=WIKIPEDIA_LANGUAGES):
    """Resolve confirmed Wikipedia articles through Wikidata's official API."""

    normalized_qids = [qid for qid in dict.fromkeys(qids) if re.fullmatch(r"Q\d+", qid or "")]
    normalized_languages = [
        language
        for language in dict.fromkeys(str(item).casefold() for item in languages)
        if re.fullmatch(r"[a-z]{2,3}", language)
    ]
    if not normalized_qids or not normalized_languages:
        return {}
    response = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": "|".join(normalized_qids[:50]),
            "props": "sitelinks",
            "sitefilter": "|".join(f"{language}wiki" for language in normalized_languages),
            "format": "json",
        },
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/json"},
        timeout=45,
    )
    response.raise_for_status()
    entities = response.json().get("entities", {})
    return {
        qid: {
            language: wikipedia_page_url(language, sitelinks[f"{language}wiki"]["title"])
            for language in normalized_languages
            if sitelinks.get(f"{language}wiki", {}).get("title")
        }
        for qid in normalized_qids[:50]
        for sitelinks in [entities.get(qid, {}).get("sitelinks", {})]
    }


def stable_fingerprint(*parts):
    normalized = "|".join(str(part).strip().lower() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def year_from_wikidata_date(value):
    match = re.match(r"^([+-]?\d+)-", value)
    return int(match.group(1)) if match else None


def point_from_wkt(value):
    match = WKT_POINT_PATTERN.match(value)
    if not match:
        return None
    return Point(float(match.group(1)), float(match.group(2)), srid=4326)


def store_wikipedia_sitelinks(entity, qid, sitelinks):
    """Persist only Wikipedia links that Wikidata confirms actually exist."""

    stored = 0
    for raw_language, raw_url in sitelinks.items():
        language = str(raw_language).strip().casefold()
        url = str(raw_url or "").strip()
        expected_prefix = f"https://{language}.wikipedia.org/wiki/"
        if not re.fullmatch(r"[a-z]{2,3}", language) or not url.startswith(expected_prefix):
            continue
        _, created = ExternalIdentifier.objects.update_or_create(
            provider=f"wikipedia-{language}",
            external_id=f"wikidata:{qid}",
            defaults={"entity": entity, "url": url},
        )
        stored += int(created)
    return stored


def time_world_query(start_year, end_year):
    if start_year < 1 or end_year > 9999:
        return None
    start = f"{start_year:04d}-01-01T00:00:00Z"
    after_end = f"{end_year + 1:04d}-01-01T00:00:00Z"
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?date ?dateProp ?sitelinks ?instance
  ?deArticle ?enArticle ?frArticle WHERE {{
  VALUES ?dateProp {{ wdt:P585 wdt:P580 wdt:P571 }}
  ?item ?dateProp ?date ; wikibase:sitelinks ?sitelinks .
  FILTER(?date >= \"{start}\"^^xsd:dateTime && ?date < \"{after_end}\"^^xsd:dateTime)
  {{ ?item wdt:P625 ?coord. }}
  UNION
  {{ ?item wdt:P276/wdt:P625 ?coord. }}
  OPTIONAL {{ ?item wdt:P31 ?instance. }}
  OPTIONAL {{ ?deArticle schema:about ?item; schema:isPartOf <https://de.wikipedia.org/>. }}
  OPTIONAL {{ ?enArticle schema:about ?item; schema:isPartOf <https://en.wikipedia.org/>. }}
  OPTIONAL {{ ?frArticle schema:about ?item; schema:isPartOf <https://fr.wikipedia.org/>. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"de,en\". }}
}}
ORDER BY DESC(?sitelinks)
LIMIT 500
"""


def ingest_wikidata_time_world(research):
    query = time_world_query(research.time_start_year, research.time_end_year)
    if not query:
        return 0
    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=60,
    )
    response.raise_for_status()
    bindings = response.json().get("results", {}).get("bindings", [])
    created = 0
    now = timezone.now()
    for binding in bindings:
        item_url = binding.get("item", {}).get("value", "")
        qid = item_url.rsplit("/", 1)[-1]
        coordinate = point_from_wkt(binding.get("coord", {}).get("value", ""))
        year = year_from_wikidata_date(binding.get("date", {}).get("value", ""))
        if not qid.startswith("Q") or coordinate is None or year is None:
            continue
        label = binding.get("itemLabel", {}).get("value", qid)
        description = binding.get("itemDescription", {}).get("value", "").strip()
        date_property = binding.get("dateProp", {}).get("value", "").rsplit("/", 1)[-1]
        instance_id = binding.get("instance", {}).get("value", "").rsplit("/", 1)[-1]
        existing = ExternalIdentifier.objects.select_related("entity").filter(provider="wikidata", external_id=qid).first()
        if existing:
            entity = existing.entity
            if label != qid and label not in entity.labels.values():
                entity.labels = {**entity.labels, "de": label}
                entity.save(update_fields=["labels", "updated_at"])
        else:
            entity = Entity.objects.create(
                canonical_name=label,
                kind=Entity.Kind.OTHER,
                labels={"de": label},
                descriptions={"de": description} if description else {},
            )
            ExternalIdentifier.objects.create(entity=entity, provider="wikidata", external_id=qid, url=item_url)
        store_wikipedia_sitelinks(
            entity,
            qid,
            {
                language: binding.get(f"{language}Article", {}).get("value", "")
                for language in WIKIPEDIA_LANGUAGES
            },
        )

        source, _ = Source.objects.update_or_create(
            provider="Wikidata",
            record_id=qid,
            url=item_url,
            defaults={
                "title": label,
                "source_type": Source.Type.COMMUNITY,
                "language": "mul",
                "license_name": "CC0 1.0",
                "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
                "publisher": "Wikidata community",
                "retrieved_at": now,
                "metadata": {
                    "date_property": date_property,
                    "sitelinks": int(binding.get("sitelinks", {}).get("value", 0)),
                    "wikidata_instance_ids": [instance_id] if instance_id.startswith("Q") else [],
                },
            },
        )
        predicate = DATE_PREDICATES.get(date_property, "dated")
        value = description or f"{label} ist für {year} datiert."
        assertion, was_created = Assertion.objects.get_or_create(
            fingerprint=stable_fingerprint(qid, predicate, year, coordinate.x, coordinate.y),
            defaults={
                "subject": entity,
                "predicate": predicate,
                "value_text": value[:1800],
                "time_start_year": year,
                "time_end_year": year,
                "time_precision": Assertion.Precision.YEAR,
                "location": coordinate,
                "spatial_precision_meters": 5000,
                "status": Assertion.Status.CANDIDATE,
                "confidence": Decimal("0.55"),
                "extraction_method": "wikidata-time-world-v1",
                "metadata": {
                    "wikidata_instance_ids": [instance_id] if instance_id.startswith("Q") else [],
                },
            },
        )
        if not was_created and instance_id.startswith("Q"):
            instance_ids = list(assertion.metadata.get("wikidata_instance_ids", []))
            if instance_id not in instance_ids:
                assertion.metadata = {**assertion.metadata, "wikidata_instance_ids": [*instance_ids, instance_id]}
                assertion.save(update_fields=["metadata", "updated_at"])
        Evidence.objects.get_or_create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.MENTIONS,
            defaults={
                "locator": f"Wikidata-Eigenschaft {date_property} für {year}",
                "excerpt": value[:700],
                "confidence": Decimal("0.55"),
            },
        )
        created += int(was_created)
    return created


def event_places_query(qid):
    if not re.fullmatch(r"Q\d+", qid or ""):
        return None
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?date ?deArticle ?enArticle ?frArticle WHERE {{
  ?item wdt:P361 wd:{qid} .
  OPTIONAL {{ ?item wdt:P585 ?date. }}
  OPTIONAL {{ ?item wdt:P580 ?date. }}
  {{ ?item wdt:P625 ?coord. }}
  UNION
  {{ ?item wdt:P276/wdt:P625 ?coord. }}
  OPTIONAL {{ ?deArticle schema:about ?item; schema:isPartOf <https://de.wikipedia.org/>. }}
  OPTIONAL {{ ?enArticle schema:about ?item; schema:isPartOf <https://en.wikipedia.org/>. }}
  OPTIONAL {{ ?frArticle schema:about ?item; schema:isPartOf <https://fr.wikipedia.org/>. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en". }}
}}
LIMIT 160
"""


def ingest_wikidata_event_places(research, event_entity, qid):
    query = event_places_query(qid)
    if not query:
        return 0
    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=60,
    )
    response.raise_for_status()
    created = 0
    now = timezone.now()
    for binding in response.json().get("results", {}).get("bindings", []):
        item_url = binding.get("item", {}).get("value", "")
        item_qid = item_url.rsplit("/", 1)[-1]
        coordinate = point_from_wkt(binding.get("coord", {}).get("value", ""))
        if not item_qid.startswith("Q") or coordinate is None:
            continue
        label = binding.get("itemLabel", {}).get("value", item_qid)
        description = binding.get("itemDescription", {}).get("value", "").strip()
        year = year_from_wikidata_date(binding.get("date", {}).get("value", ""))
        existing = ExternalIdentifier.objects.select_related("entity").filter(
            provider="wikidata", external_id=item_qid
        ).first()
        if existing:
            entity = existing.entity
            entity.kind = Entity.Kind.EVENT
            if label != item_qid:
                entity.canonical_name = label
                entity.labels = {**entity.labels, "de": label}
            if description:
                entity.descriptions = {**entity.descriptions, "de": description}
            entity.save(update_fields=["kind", "canonical_name", "labels", "descriptions", "updated_at"])
        else:
            entity = Entity.objects.create(
                canonical_name=label,
                kind=Entity.Kind.EVENT,
                labels={"de": label},
                descriptions={"de": description} if description else {},
            )
            ExternalIdentifier.objects.create(
                entity=entity,
                provider="wikidata",
                external_id=item_qid,
                url=f"https://www.wikidata.org/wiki/{item_qid}",
            )
        store_wikipedia_sitelinks(
            entity,
            item_qid,
            {
                language: binding.get(f"{language}Article", {}).get("value", "")
                for language in WIKIPEDIA_LANGUAGES
            },
        )
        source, _ = Source.objects.update_or_create(
            provider="Wikidata",
            record_id=item_qid,
            url=f"https://www.wikidata.org/wiki/{item_qid}",
            defaults={
                "title": label,
                "source_type": Source.Type.COMMUNITY,
                "language": "mul",
                "license_name": "CC0 1.0",
                "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
                "publisher": "Wikidata community",
                "retrieved_at": now,
                "metadata": {"relation_property": "P361", "parent_event": qid},
            },
        )
        start_year = year if year is not None else research.time_start_year
        end_year = year if year is not None else research.time_end_year
        confidence = Decimal("0.78") if year is not None else Decimal("0.62")
        assertion, was_created = Assertion.objects.get_or_create(
            fingerprint=stable_fingerprint(qid, item_qid, "related-to-event", start_year, end_year, coordinate.x, coordinate.y),
            defaults={
                "subject": entity,
                "object_entity": event_entity,
                "predicate": "related-to-event",
                "value_text": description or f"{label} ist in Wikidata als Teil von {event_entity.canonical_name} verknüpft.",
                "time_start_year": start_year,
                "time_end_year": end_year,
                "time_precision": Assertion.Precision.YEAR if year is not None else Assertion.Precision.RANGE,
                "location": coordinate,
                "spatial_precision_meters": 5000,
                "status": Assertion.Status.CANDIDATE,
                "confidence": confidence,
                "extraction_method": "wikidata-event-places-v1",
            },
        )
        Evidence.objects.get_or_create(
            assertion=assertion,
            source=source,
            relation=Evidence.Relation.SUPPORTS,
            defaults={
                "locator": f"Wikidata-Eigenschaft P361 (Teil von {qid})",
                "excerpt": description or label,
                "confidence": confidence,
            },
        )
        created += int(was_created)
    return created
