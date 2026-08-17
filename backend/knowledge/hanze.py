import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry

from .models import Assertion, EnvironmentalDataset, EnvironmentalEvent


HANZE_VECTOR_URL = "https://zenodo.org/records/8410025/files/HANZE_floods_regions_2021.zip?download=1"

TYPE_LABELS = {
    "Coastal": {
        "event_type": EnvironmentalEvent.Type.STORM_SURGE,
        "en": "Coastal flood",
        "de": "Küstenhochwasser",
        "fr": "Submersion côtière",
    },
    "River": {
        "event_type": EnvironmentalEvent.Type.FLOOD,
        "en": "River flood",
        "de": "Flusshochwasser",
        "fr": "Crue fluviale",
    },
    "Flash": {
        "event_type": EnvironmentalEvent.Type.FLOOD,
        "en": "Flash flood",
        "de": "Sturzflut",
        "fr": "Crue soudaine",
    },
    "River/Coastal": {
        "event_type": EnvironmentalEvent.Type.FLOOD,
        "en": "Compound river and coastal flood",
        "de": "Zusammengesetztes Fluss- und Küstenhochwasser",
        "fr": "Crue fluviale et côtière combinée",
    },
}


def feature_value(feature, field, default=""):
    try:
        value = feature.get(field)
    except (KeyError, TypeError):
        return default
    if value is None:
        return default
    return str(value).strip()


def integer_value(feature, field):
    raw = feature_value(feature, field)
    try:
        return int(Decimal(raw)) if raw else None
    except (InvalidOperation, ValueError):
        return None


def decimal_value(feature, field):
    raw = feature_value(feature, field)
    try:
        return float(Decimal(raw)) if raw else None
    except (InvalidOperation, ValueError):
        return None


def iso_date(feature, prefix, fallback_year):
    year = integer_value(feature, f"{prefix}_Y") or fallback_year
    month = integer_value(feature, f"{prefix}_M")
    day = integer_value(feature, f"{prefix}_D")
    if month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if month:
        return f"{year:04d}-{month:02d}"
    return str(year)


def localized_event_labels(flood_type, country, year):
    labels = TYPE_LABELS.get(flood_type, TYPE_LABELS["River"])
    return {
        language: f"{labels[language]} · {country} ({year})"
        for language in ("en", "de", "fr")
    }


def event_description(feature):
    parts = []
    source = feature_value(feature, "Source")
    cause = feature_value(feature, "Cause")
    notes = feature_value(feature, "Notes")
    if source:
        parts.append(f"Rivers or flood source: {source}.")
    if cause:
        parts.append(f"Reported cause: {cause}.")
    if notes:
        parts.append(notes)
    return " ".join(parts)


def feature_geometry(feature):
    if not feature.geom:
        return None
    geometry = feature.geom.clone()
    geometry.transform(4326)
    geos = GEOSGeometry(geometry.wkt, srid=4326)
    # HANZE maps affected administrative regions, not the exact inundated area.
    # A light simplification keeps proximity searches quick without implying precision.
    return geos.simplify(0.005, preserve_topology=True)


def import_hanze_vector(vector_path, *, limit=None, stdout=None):
    dataset = EnvironmentalDataset.objects.get(slug="hanze-v2-1-flood-impacts")
    layer = DataSource(str(vector_path))[0]
    created = updated = skipped = 0
    for index, feature in enumerate(layer):
        if limit is not None and index >= limit:
            break
        external_id = feature_value(feature, "ID")
        year = integer_value(feature, "Year") or integer_value(feature, "Start_Y")
        country = feature_value(feature, "Country")
        flood_type = feature_value(feature, "Type")
        if not external_id or not year or not feature.geom:
            skipped += 1
            continue
        end_year = integer_value(feature, "End_Y") or year
        labels = localized_event_labels(flood_type, country, year)
        type_info = TYPE_LABELS.get(flood_type, TYPE_LABELS["River"])
        defaults = {
            "event_type": type_info["event_type"],
            "name": labels["en"],
            "description": event_description(feature),
            "geometry": feature_geometry(feature),
            "spatial_resolution_meters": 25000,
            "time_start_year": year,
            "time_end_year": end_year,
            "time_precision": Assertion.Precision.DAY,
            "temporal_uncertainty_years": 0,
            "status": Assertion.Status.VERIFIED,
            "confidence": Decimal("0.90"),
            "metadata": {
                "labels": labels,
                "dates": {
                    "start": iso_date(feature, "Start", year),
                    "end": iso_date(feature, "End", end_year),
                },
                "hanze_type": flood_type,
                "flood_source": feature_value(feature, "Source"),
                "cause": feature_value(feature, "Cause"),
                "notes": feature_value(feature, "Notes"),
                "references": feature_value(feature, "References"),
                "affected_regions": feature_value(feature, "Region2021"),
                "area_flooded_km2": decimal_value(feature, "Area"),
                "fatalities": integer_value(feature, "Fatalities"),
                "persons_affected": integer_value(feature, "Persons"),
                "losses_2020_euro": decimal_value(feature, "LossesEuro"),
                "spatial_note": (
                    "Geometry represents affected administrative regions, not the exact inundation extent."
                ),
            },
        }
        _, was_created = EnvironmentalEvent.objects.update_or_create(
            dataset=dataset,
            external_id=external_id,
            defaults=defaults,
        )
        created += int(was_created)
        updated += int(not was_created)
        if stdout and (created + updated) % 250 == 0:
            stdout.write(f"HANZE: {created + updated} Ereignisse verarbeitet")
    return {"created": created, "updated": updated, "skipped": skipped}


def download_and_import_hanze(*, url=HANZE_VECTOR_URL, limit=None, stdout=None):
    with tempfile.TemporaryDirectory(prefix="hanze-") as directory:
        archive_path = Path(directory) / "hanze.zip"
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        archive_path.write_bytes(response.content)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(directory)
        vector_path = next(Path(directory).glob("*.shp"))
        return import_hanze_vector(vector_path, limit=limit, stdout=stdout)
