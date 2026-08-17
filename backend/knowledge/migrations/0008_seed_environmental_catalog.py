from decimal import Decimal

from django.contrib.gis.geos import Point
from django.db import migrations
from django.utils import timezone


def seed_environmental_catalog(apps, schema_editor):
    Source = apps.get_model("knowledge", "Source")
    EnvironmentalDataset = apps.get_model("knowledge", "EnvironmentalDataset")
    EnvironmentalEvent = apps.get_model("knowledge", "EnvironmentalEvent")
    EnvironmentalObservation = apps.get_model("knowledge", "EnvironmentalObservation")

    entries = [
        {
            "slug": "smithsonian-gvp-eruptions",
            "source": {
                "provider": "Smithsonian Global Volcanism Program",
                "record_id": "VOTW-WFS",
                "url": "https://volcano.si.edu/database/webservices.cfm",
                "title": "Volcanoes of the World – Holocene Eruptions",
                "source_type": "institution",
                "language": "en",
                "license_name": "Smithsonian Terms of Use – attribution required",
                "license_url": "https://volcano.si.edu/gvp_termsofuse.cfm",
                "publisher": "Smithsonian Institution, Global Volcanism Program",
            },
            "dataset": {
                "title": "Smithsonian Holocene Eruptions",
                "provider": "Smithsonian Global Volcanism Program",
                "data_kind": "vector",
                "storage_kind": "external",
                "asset_uri": "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/wfs?request=GetCapabilities",
                "file_format": "OGC WFS / GeoJSON",
                "variable_name": "eruption",
                "time_start_year": -10000,
                "time_end_year": 2026,
                "spatial_resolution_text": "Vulkan- beziehungsweise Eruptionsstandort; Genauigkeit je Datensatz",
                "metadata": {"role": "event_catalogue", "import_strategy": "WFS feature subsets"},
            },
        },
        {
            "slug": "evolv2k-v2",
            "source": {
                "provider": "eVolv2k",
                "record_id": "10.1594/WDCC/eVolv2k_v2",
                "url": "https://doi.org/10.1594/WDCC/eVolv2k_v2",
                "title": "Volcanic stratospheric sulfur injections and aerosol optical depth, 500 BCE–1900 CE",
                "source_type": "scholarly",
                "language": "en",
                "license_name": "Datensatzlizenz siehe WDCC; Fachartikel CC BY 3.0",
                "license_url": "https://doi.org/10.5194/essd-9-809-2017",
                "publisher": "World Data Center for Climate / Earth System Science Data",
            },
            "dataset": {
                "title": "eVolv2k volcanic forcing reconstruction",
                "provider": "Toohey & Sigl / WDCC",
                "data_kind": "reconstruction",
                "storage_kind": "external",
                "asset_uri": "https://doi.org/10.1594/WDCC/eVolv2k_v2",
                "file_format": "NetCDF / ASCII",
                "variable_name": "VSSI / SAOD",
                "unit": "Tg S / dimensionslos",
                "time_start_year": -500,
                "time_end_year": 1900,
                "spatial_resolution_text": "Breitengrad- und zeitaufgelöste globale Rekonstruktion",
                "metadata": {"role": "forcing_reconstruction", "large_assets": "object_storage"},
            },
        },
        {
            "slug": "old-world-drought-atlas",
            "source": {
                "provider": "NOAA NCEI / Old World Drought Atlas",
                "record_id": "NCEI-19419",
                "url": "https://www.ncei.noaa.gov/access/paleo-search/study/19419",
                "title": "Old World Drought Atlas",
                "source_type": "scholarly",
                "language": "en",
                "license_name": "NOAA/NCEI data access – citation required",
                "license_url": "https://www.drought.gov/data-maps-tools/old-world-drought-atlas",
                "publisher": "NOAA National Centers for Environmental Information",
            },
            "dataset": {
                "title": "Old World Drought Atlas – annual summer PDSI",
                "provider": "NOAA NCEI / Cook et al.",
                "data_kind": "raster",
                "storage_kind": "external",
                "asset_uri": "https://www.ncei.noaa.gov/access/paleo-search/study/19419",
                "file_format": "NetCDF-4 / ASCII",
                "variable_name": "JJA PDSI",
                "unit": "PDSI index",
                "time_start_year": 0,
                "time_end_year": 2012,
                "spatial_resolution_text": "Jährliches Gitter über Europa und dem Mittelmeerraum",
                "metadata": {"role": "drought_reconstruction", "large_assets": "cog_or_netcdf_object_storage"},
            },
        },
        {
            "slug": "dwd-cdc-historical-climate",
            "source": {
                "provider": "Deutscher Wetterdienst Climate Data Center",
                "record_id": "DWD-CDC-HIST",
                "url": "https://opendata.dwd.de/climate_environment/CDC/",
                "title": "Historische Klima- und Wetterbeobachtungen Deutschlands",
                "source_type": "institution",
                "language": "de",
                "license_name": "CC BY 4.0",
                "license_url": "https://www.dwd.de/DE/leistungen/opendata/faqs_opendata.html",
                "publisher": "Deutscher Wetterdienst",
            },
            "dataset": {
                "title": "DWD CDC – historische Stations- und Rasterdaten",
                "provider": "Deutscher Wetterdienst",
                "data_kind": "station",
                "storage_kind": "external",
                "asset_uri": "https://opendata.dwd.de/climate_environment/CDC/",
                "file_format": "ZIP / ASCII / NetCDF / GeoTIFF",
                "variable_name": "Temperatur, Niederschlag, Frost, Hitze und Wettererscheinungen",
                "time_start_year": 1719,
                "time_end_year": 2026,
                "spatial_resolution_text": "Stationsabhängig; Rasterauflösung produktabhängig",
                "metadata": {"role": "instrumental_observations", "large_assets": "object_storage"},
            },
        },
    ]

    datasets = {}
    for entry in entries:
        source_values = entry["source"]
        source, _ = Source.objects.update_or_create(
            provider=source_values["provider"],
            record_id=source_values["record_id"],
            url=source_values["url"],
            defaults={**source_values, "retrieved_at": timezone.now()},
        )
        dataset, _ = EnvironmentalDataset.objects.update_or_create(
            slug=entry["slug"],
            defaults={**entry["dataset"], "source": source},
        )
        datasets[entry["slug"]] = dataset

    tambora, _ = EnvironmentalEvent.objects.update_or_create(
        dataset=datasets["smithsonian-gvp-eruptions"],
        external_id="264040:1815",
        defaults={
            "event_type": "volcano",
            "name": "Ausbruch des Tambora",
            "description": "Großer explosiver Ausbruch des Tambora im April 1815.",
            "geometry": Point(118.0, -8.25, srid=4326),
            "spatial_resolution_meters": 10000,
            "time_start_year": 1815,
            "time_end_year": 1815,
            "time_precision": "year",
            "temporal_uncertainty_years": 0,
            "status": "verified",
            "confidence": Decimal("0.980"),
            "metadata": {"vei": 7, "month": 4, "scope": "eruption_location"},
        },
    )
    EnvironmentalObservation.objects.update_or_create(
        dataset=datasets["evolv2k-v2"],
        external_id="tambora-1815-vssi",
        defaults={
            "event": tambora,
            "method": "reconstruction",
            "variable": "Stratosphärischer Schwefeleintrag durch Vulkane",
            "value": Decimal("28.08000000"),
            "unit": "Tg S",
            "spatial_scope": "global",
            "time_start_year": 1815,
            "time_end_year": 1816,
            "time_precision": "range",
            "temporal_uncertainty_years": 1,
            "aggregation": "Rekonstruierter zentraler Schätzwert",
            "confidence": Decimal("0.850"),
            "status": "candidate",
            "asset_uri": "https://doi.org/10.1594/WDCC/eVolv2k_v2",
            "metadata": {
                "original_variable": "Volcanic stratospheric sulfur injection",
                "uncertainty_note": "Rekonstruktion aus Eisbohrkernen; Unsicherheitsintervall ist dem Originaldatensatz zu entnehmen.",
                "demo_value": True,
            },
        },
    )


def unseed_environmental_catalog(apps, schema_editor):
    EnvironmentalDataset = apps.get_model("knowledge", "EnvironmentalDataset")
    EnvironmentalEvent = apps.get_model("knowledge", "EnvironmentalEvent")
    EnvironmentalObservation = apps.get_model("knowledge", "EnvironmentalObservation")
    datasets = EnvironmentalDataset.objects.filter(
        slug__in=[
            "smithsonian-gvp-eruptions",
            "evolv2k-v2",
            "old-world-drought-atlas",
            "dwd-cdc-historical-climate",
        ]
    )
    EnvironmentalObservation.objects.filter(dataset__in=datasets).delete()
    EnvironmentalEvent.objects.filter(dataset__in=datasets).delete()
    EnvironmentalDataset.objects.filter(
        slug__in=[
            "smithsonian-gvp-eruptions",
            "evolv2k-v2",
            "old-world-drought-atlas",
            "dwd-cdc-historical-climate",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0007_environmentaldataset_environmentalevent_and_more")]

    operations = [migrations.RunPython(seed_environmental_catalog, unseed_environmental_catalog)]
