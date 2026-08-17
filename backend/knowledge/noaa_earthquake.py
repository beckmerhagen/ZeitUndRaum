import re
from decimal import Decimal

import requests
from django.contrib.gis.geos import Point
from django.utils import timezone

from .models import Assertion, EnvironmentalDataset, EnvironmentalEvent, Source


NOAA_EARTHQUAKE_QUERY_URL = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/"
    "web_mercator/hazards/MapServer/5/query"
)
NOAA_EARTHQUAKE_DATASET_URL = (
    "https://www.ncei.noaa.gov/products/natural-hazards/"
    "tsunamis-earthquakes-volcanoes/earthquakes"
)


def earthquake_dataset():
    source, _ = Source.objects.update_or_create(
        provider="NOAA NCEI / WDS",
        record_id="doi:10.7289/V5TD9V7K",
        url=NOAA_EARTHQUAKE_DATASET_URL,
        defaults={
            "title": "NCEI/WDS Global Significant Earthquake Database",
            "source_type": Source.Type.INSTITUTION,
            "language": "en",
            "license_name": "NOAA/NCEI data access – citation required",
            "license_url": "https://www.ncei.noaa.gov/disclaimer",
            "publisher": "NOAA National Centers for Environmental Information",
            "retrieved_at": timezone.now(),
        },
    )
    dataset, _ = EnvironmentalDataset.objects.update_or_create(
        slug="noaa-global-significant-earthquakes",
        defaults={
            "title": "NCEI/WDS Global Significant Earthquake Database",
            "provider": "NOAA NCEI / WDS",
            "source": source,
            "data_kind": EnvironmentalDataset.DataKind.VECTOR,
            "storage_kind": EnvironmentalDataset.StorageKind.DATABASE,
            "asset_uri": NOAA_EARTHQUAKE_QUERY_URL,
            "file_format": "ArcGIS Feature Service / GeoJSON",
            "variable_name": "Significant earthquake events",
            "time_start_year": -2150,
            "time_end_year": timezone.now().year,
            "spatial_resolution_text": "Documented or reconstructed earthquake epicentre",
            "metadata": {
                "role": "event_catalogue",
                "doi": "10.7289/V5TD9V7K",
                "layer": 5,
                "selection": "Earthquakes meeting the NCEI significance criteria",
            },
        },
    )
    return dataset


def fetch_noaa_earthquake_features(*, country="", limit=None, page_size=2000):
    where = "1=1"
    if country:
        safe_country = country.upper().replace("'", "''")
        where = f"UPPER(COUNTRY)='{safe_country}'"
    offset = 0
    collected = []
    while limit is None or len(collected) < limit:
        count = min(page_size, limit - len(collected)) if limit is not None else page_size
        response = requests.get(
            NOAA_EARTHQUAKE_QUERY_URL,
            params={
                "where": where,
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": count,
                "f": "geojson",
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        features = payload.get("features", [])
        collected.extend(features)
        if not features or not payload.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(features)
    return collected[:limit] if limit is not None else collected


def _clean_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(text.split())


def _historical_date(properties):
    year = int(properties["YEAR"])
    month = properties.get("MONTH")
    day = properties.get("DAY")
    if year <= 0:
        return ""
    if month and day:
        return f"{year:04d}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year:04d}-{int(month):02d}"
    return str(year)


def _description(properties, language):
    magnitude = properties.get("EQ_MAGNITUDE")
    depth = properties.get("EQ_DEPTH")
    fatalities = properties.get("DEATHS_TOTAL") or properties.get("DEATHS")
    if language == "de":
        parts = ["Im globalen NOAA/NCEI-Katalog als bedeutendes Erdbeben erfasst."]
        if magnitude is not None:
            parts.append(f"Magnitude: {float(magnitude):g}.")
        if depth is not None:
            parts.append(f"Herdtiefe: {float(depth):g} km.")
        if fatalities is not None:
            parts.append(f"Dokumentierte Todesopfer: {int(fatalities)}.")
        return " ".join(parts)
    if language == "fr":
        parts = ["Répertorié comme séisme important dans le catalogue mondial NOAA/NCEI."]
        if magnitude is not None:
            parts.append(f"Magnitude : {float(magnitude):g}.")
        if depth is not None:
            parts.append(f"Profondeur : {float(depth):g} km.")
        if fatalities is not None:
            parts.append(f"Décès documentés : {int(fatalities)}.")
        return " ".join(parts)
    parts = ["Listed as a significant earthquake in the global NOAA/NCEI catalogue."]
    if magnitude is not None:
        parts.append(f"Magnitude: {float(magnitude):g}.")
    if depth is not None:
        parts.append(f"Depth: {float(depth):g} km.")
    if fatalities is not None:
        parts.append(f"Documented fatalities: {int(fatalities)}.")
    return " ".join(parts)


def import_noaa_earthquake_features(features, *, stdout=None):
    dataset = earthquake_dataset()
    created = updated = skipped = 0
    for feature in features:
        properties = feature.get("properties") or {}
        event_id = properties.get("ID")
        year = properties.get("YEAR")
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if event_id is None or year is None or len(coordinates) < 2:
            skipped += 1
            continue
        location = _clean_text(properties.get("LOCATION_NAME")) or _clean_text(properties.get("COUNTRY"))
        if not location:
            location = "Unspecified location"
        country = _clean_text(properties.get("COUNTRY"))
        year = int(year)
        english_name = f"Earthquake · {location} ({year})"
        source_url = _clean_text(properties.get("URL")) or NOAA_EARTHQUAKE_DATASET_URL
        date = _historical_date(properties)
        precision = (
            Assertion.Precision.DAY
            if properties.get("MONTH") and properties.get("DAY")
            else Assertion.Precision.MONTH
            if properties.get("MONTH")
            else Assertion.Precision.YEAR
        )
        magnitude = properties.get("EQ_MAGNITUDE")
        depth = properties.get("EQ_DEPTH")
        fatalities = properties.get("DEATHS_TOTAL") or properties.get("DEATHS")
        defaults = {
            "event_type": EnvironmentalEvent.Type.EARTHQUAKE,
            "name": english_name,
            "description": _description(properties, "en"),
            "geometry": Point(float(coordinates[0]), float(coordinates[1]), srid=4326),
            "spatial_resolution_meters": 10000,
            "time_start_year": year,
            "time_end_year": year,
            "time_precision": precision,
            "temporal_uncertainty_years": 0,
            "status": Assertion.Status.VERIFIED,
            "confidence": Decimal("0.950"),
            "metadata": {
                "labels": {
                    "en": english_name,
                    "de": f"Erdbeben · {location} ({year})",
                    "fr": f"Séisme · {location} ({year})",
                },
                "descriptions": {
                    "en": _description(properties, "en"),
                    "de": _description(properties, "de"),
                    "fr": _description(properties, "fr"),
                },
                "country": country,
                "region": _clean_text(properties.get("REGION")),
                "location": location,
                "dates": {"start": date} if date else {},
                "magnitude": float(magnitude) if magnitude is not None else None,
                "depth_km": float(depth) if depth is not None else None,
                "intensity": properties.get("INTENSITY"),
                "fatalities": int(fatalities) if fatalities is not None else None,
                "damage_description": _clean_text(
                    properties.get("DAMAGE_TOTAL_DESCRIPTION") or properties.get("DAMAGE_DESCRIPTION")
                ),
                "tsunami_reported": bool(properties.get("FLAG_TSUNAMI")),
                "volcanic_event_reported": bool(properties.get("FLAG_VOL_EVENT")),
                "notes": _clean_text(properties.get("COMMENTS"))[:1000],
                "event_id": str(event_id),
                "source_urls": [source_url],
                "spatial_note": "The point is the documented or reconstructed epicentre; historical coordinates may be approximate.",
            },
        }
        _, was_created = EnvironmentalEvent.objects.update_or_create(
            dataset=dataset,
            external_id=f"earthquake:{event_id}",
            defaults=defaults,
        )
        created += int(was_created)
        updated += int(not was_created)
    if stdout:
        stdout.write(f"NOAA Erdbeben: {created + updated} Ereignisse verarbeitet")
    return {"created": created, "updated": updated, "skipped": skipped, "events": len(features)}


def download_and_import_noaa_earthquakes(*, country="", limit=None, stdout=None):
    features = fetch_noaa_earthquake_features(country=country, limit=limit)
    return import_noaa_earthquake_features(features, stdout=stdout)
