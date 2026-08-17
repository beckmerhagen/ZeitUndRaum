import re
from collections import defaultdict
from decimal import Decimal

import requests
from django.contrib.gis.geos import MultiPoint, Point
from django.utils import timezone

from .models import Assertion, EnvironmentalDataset, EnvironmentalEvent, Source


NOAA_TSUNAMI_QUERY_URL = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/"
    "web_mercator/hazards/MapServer/4/query"
)
NOAA_TSUNAMI_DATASET_URL = (
    "https://www.ncei.noaa.gov/products/natural-hazards/"
    "tsunamis-earthquakes-volcanoes/tsunamis"
)


def tsunami_dataset():
    source, _ = Source.objects.update_or_create(
        provider="NOAA NCEI / WDS",
        record_id="doi:10.7289/V5PN93H7",
        url=NOAA_TSUNAMI_DATASET_URL,
        defaults={
            "title": "NCEI/WDS Global Historical Tsunami Database",
            "source_type": Source.Type.INSTITUTION,
            "language": "en",
            "license_name": "NOAA/NCEI data access – citation required",
            "license_url": "https://www.ncei.noaa.gov/disclaimer",
            "publisher": "NOAA National Centers for Environmental Information",
            "retrieved_at": timezone.now(),
        },
    )
    dataset, _ = EnvironmentalDataset.objects.update_or_create(
        slug="noaa-global-historical-tsunami-observations",
        defaults={
            "title": "NCEI/WDS Global Historical Tsunami Database – observed impacts",
            "provider": "NOAA NCEI / WDS",
            "source": source,
            "data_kind": EnvironmentalDataset.DataKind.VECTOR,
            "storage_kind": EnvironmentalDataset.StorageKind.DATABASE,
            "asset_uri": NOAA_TSUNAMI_QUERY_URL,
            "file_format": "ArcGIS Feature Service / GeoJSON",
            "variable_name": "Tsunami run-up and observation locations",
            "time_start_year": -2100,
            "time_end_year": timezone.now().year,
            "spatial_resolution_text": "Documented observation or survey location",
            "metadata": {
                "role": "event_catalogue",
                "doi": "10.7289/V5PN93H7",
                "layer": 4,
                "grouping": "tsunami event and affected country",
            },
        },
    )
    return dataset


def fetch_noaa_tsunami_features(*, country="", limit=None, page_size=2000):
    where = "1=1"
    if country:
        safe_country = country.upper().replace("'", "''")
        where = f"UPPER(COUNTRY)='{safe_country}'"
    offset = 0
    collected = []
    while limit is None or len(collected) < limit:
        count = min(page_size, limit - len(collected)) if limit is not None else page_size
        response = requests.get(
            NOAA_TSUNAMI_QUERY_URL,
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


def _event_geometry(features):
    unique = {}
    for feature in features:
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        point = Point(float(coordinates[0]), float(coordinates[1]), srid=4326)
        unique[(round(point.x, 6), round(point.y, 6))] = point
    points = list(unique.values())
    if not points:
        return None
    return points[0] if len(points) == 1 else MultiPoint(*points, srid=4326)


def import_noaa_tsunami_features(features, *, stdout=None):
    dataset = tsunami_dataset()
    grouped = defaultdict(list)
    for feature in features:
        properties = feature.get("properties") or {}
        event_id = properties.get("TSEVENT_ID")
        year = properties.get("YEAR")
        country = _clean_text(properties.get("COUNTRY"))
        if event_id is None or year is None or not country:
            continue
        grouped[(str(event_id), country, int(year))].append(feature)

    created = updated = skipped = 0
    for (event_id, country, year), observations in grouped.items():
        geometry = _event_geometry(observations)
        if geometry is None:
            skipped += 1
            continue
        properties = [item.get("properties") or {} for item in observations]
        heights = [float(item["RUNUP_HT"]) for item in properties if item.get("RUNUP_HT") is not None]
        fatalities = [int(item["DEATHS"]) for item in properties if item.get("DEATHS") is not None]
        locations = sorted({_clean_text(item.get("LOCATION_NAME")) for item in properties if item.get("LOCATION_NAME")})
        source_urls = sorted({item.get("TSEVENT_URL") for item in properties if item.get("TSEVENT_URL")})
        dates = sorted({_clean_text(item.get("DATE_STRING")) for item in properties if item.get("DATE_STRING")})
        comments = [_clean_text(item.get("COMMENTS")) for item in properties if item.get("COMMENTS")]
        country_title = country.title()
        name = f"Tsunami observations · {country_title} ({year})"
        description = (
            f"{len(observations)} documented tsunami observations in {country_title}."
            + (f" Maximum recorded water height: {max(heights):g} m." if heights else "")
        )
        defaults = {
            "event_type": EnvironmentalEvent.Type.TSUNAMI,
            "name": name,
            "description": description,
            "geometry": geometry,
            "spatial_resolution_meters": 1000,
            "time_start_year": year,
            "time_end_year": year,
            "time_precision": Assertion.Precision.DAY if dates else Assertion.Precision.YEAR,
            "temporal_uncertainty_years": 0,
            "status": Assertion.Status.VERIFIED,
            "confidence": Decimal("0.950"),
            "metadata": {
                "labels": {
                    "en": name,
                    "de": f"Tsunami-Beobachtungen · {country_title} ({year})",
                    "fr": f"Observations de tsunami · {country_title} ({year})",
                },
                "descriptions": {
                    "en": description,
                    "de": f"{len(observations)} dokumentierte Tsunami-Beobachtungen in {country_title}.",
                    "fr": f"{len(observations)} observations de tsunami documentées en {country_title}.",
                },
                "country": country,
                "dates": {"start": dates[0]} if dates else {},
                "observation_count": len(observations),
                "locations": locations,
                "maximum_water_height_m": max(heights) if heights else None,
                "fatalities_at_observation_sites": sum(fatalities) if fatalities else None,
                "notes": comments[0][:1000] if comments else "",
                "event_id": event_id,
                "source_urls": source_urls,
                "spatial_note": "Geometry represents documented tsunami observation sites in the affected country.",
            },
        }
        _, was_created = EnvironmentalEvent.objects.update_or_create(
            dataset=dataset,
            external_id=f"event-country:{event_id}:{country}",
            defaults=defaults,
        )
        created += int(was_created)
        updated += int(not was_created)
    if stdout:
        stdout.write(f"NOAA Tsunami: {created + updated} Ereignis-Land-Gruppen verarbeitet")
    return {"created": created, "updated": updated, "skipped": skipped, "observations": len(features)}


def download_and_import_noaa_tsunamis(*, country="", limit=None, stdout=None):
    features = fetch_noaa_tsunami_features(country=country, limit=limit)
    return import_noaa_tsunami_features(features, stdout=stdout)
