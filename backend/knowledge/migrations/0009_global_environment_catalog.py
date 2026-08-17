from django.db import migrations, models
from django.utils import timezone


DATASETS = [
    {
        "slug": "nasa-power-merra2-monthly",
        "source": {
            "provider": "NASA POWER",
            "record_id": "POWER-MONTHLY-MERRA2",
            "url": "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/",
            "title": "NASA POWER Monthly and Annual API",
            "source_type": "institution",
            "language": "en",
            "license_name": "NASA data – citation requested",
            "license_url": "https://power.larc.nasa.gov/docs/referencing/",
            "publisher": "NASA Langley Research Center",
        },
        "dataset": {
            "title": "NASA POWER – monthly MERRA-2 climate at a point",
            "provider": "NASA POWER / GMAO MERRA-2",
            "data_kind": "raster",
            "storage_kind": "external",
            "asset_uri": "https://power.larc.nasa.gov/api/temporal/monthly/point",
            "file_format": "JSON / CSV / NetCDF",
            "variable_name": "Temperature and precipitation",
            "unit": "°C / mm",
            "time_start_year": 1981,
            "time_end_year": 2025,
            "reference_period_start_year": 1991,
            "reference_period_end_year": 2020,
            "spatial_resolution_meters": 55000,
            "spatial_resolution_text": "Global MERRA-2 grid, 0.5° × 0.625°; not a local station",
            "metadata": {"role": "global_climate_table", "api": "monthly_point"},
        },
    },
    {
        "slug": "hanze-v2-1-flood-impacts",
        "source": {
            "provider": "HANZE / Earth System Science Data",
            "record_id": "10.5281/zenodo.8410025",
            "url": "https://doi.org/10.5194/essd-16-5145-2024",
            "title": "HANZE v2.1: flood impacts in Europe from 1870 to 2020",
            "source_type": "scholarly",
            "language": "en",
            "license_name": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "publisher": "Copernicus Publications / Zenodo",
        },
        "dataset": {
            "title": "HANZE v2.1 – riverine, flash, coastal and compound floods",
            "provider": "Paprotny, Terefenko & Śledziowski",
            "data_kind": "vector",
            "storage_kind": "external",
            "asset_uri": "https://doi.org/10.5281/zenodo.8410025",
            "file_format": "CSV / GIS vector",
            "variable_name": "Flood event, type, dates, affected area and impacts",
            "time_start_year": 1870,
            "time_end_year": 2020,
            "spatial_resolution_text": "European NUTS-3-like affected regions; daily to monthly dates",
            "metadata": {"role": "flood_event_catalogue", "event_types": ["riverine", "flash", "coastal", "compound"]},
        },
    },
    {
        "slug": "global-flood-database-v1",
        "source": {
            "provider": "Global Flood Database",
            "record_id": "GLOBAL_FLOOD_DB_MODIS_EVENTS_V1",
            "url": "https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_EVENTS_V1",
            "title": "Global Flood Database v1 (2000–2018)",
            "source_type": "scholarly",
            "language": "en",
            "license_name": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "publisher": "Cloud to Street / Dartmouth Flood Observatory",
        },
        "dataset": {
            "title": "Global Flood Database – satellite-observed flood extent and duration",
            "provider": "Cloud to Street / Dartmouth Flood Observatory",
            "data_kind": "raster",
            "storage_kind": "external",
            "asset_uri": "earthengine://GLOBAL_FLOOD_DB/MODIS_EVENTS/V1",
            "file_format": "Earth Engine ImageCollection",
            "variable_name": "Flood extent, duration and observation quality",
            "unit": "binary / days / percent",
            "time_start_year": 2000,
            "time_end_year": 2018,
            "spatial_resolution_meters": 250,
            "spatial_resolution_text": "MODIS event maps at 250 m; 913 quality-controlled flood events",
            "metadata": {"role": "global_flood_extent", "large_assets": "earth_engine_or_object_storage"},
        },
    },
    {
        "slug": "global-channel-belt-1984-2020",
        "source": {
            "provider": "Global Channel Belt",
            "record_id": "10.1038/s41467-023-37852-8",
            "url": "https://doi.org/10.1038/s41467-023-37852-8",
            "title": "Global scale analysis on the extent of river channel belts",
            "source_type": "scholarly",
            "language": "en",
            "license_name": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "publisher": "Nature Communications",
        },
        "dataset": {
            "title": "Global Channel Belt – active channels and migration 1984–2020",
            "provider": "Nyberg et al. / Landsat Global Surface Water",
            "data_kind": "raster",
            "storage_kind": "external",
            "asset_uri": "https://doi.org/10.1038/s41467-023-37852-8",
            "file_format": "GeoTIFF / interactive map",
            "variable_name": "Active river, oxbow lake, channel migration and channel belt",
            "time_start_year": 1984,
            "time_end_year": 2020,
            "spatial_resolution_meters": 30,
            "spatial_resolution_text": "30 m Landsat input; effective channel-belt detection is coarser",
            "metadata": {"role": "river_course_change", "large_assets": "cog_object_storage"},
        },
    },
]


def add_catalogues(apps, schema_editor):
    Source = apps.get_model("knowledge", "Source")
    EnvironmentalDataset = apps.get_model("knowledge", "EnvironmentalDataset")
    for entry in DATASETS:
        source_values = entry["source"]
        source, _ = Source.objects.update_or_create(
            provider=source_values["provider"],
            record_id=source_values["record_id"],
            url=source_values["url"],
            defaults={**source_values, "retrieved_at": timezone.now()},
        )
        EnvironmentalDataset.objects.update_or_create(
            slug=entry["slug"],
            defaults={**entry["dataset"], "source": source},
        )


def remove_catalogues(apps, schema_editor):
    EnvironmentalDataset = apps.get_model("knowledge", "EnvironmentalDataset")
    EnvironmentalDataset.objects.filter(slug__in=[entry["slug"] for entry in DATASETS]).delete()


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0008_seed_environmental_catalog")]

    operations = [
        migrations.AlterField(
            model_name="environmentalevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("volcano", "Vulkanausbruch"),
                    ("storm_surge", "Sturmflut"),
                    ("drought", "Dürre"),
                    ("heatwave", "Hitzewelle"),
                    ("frost", "Frost / Kälteperiode"),
                    ("flood", "Hochwasser"),
                    ("river_course_change", "Flusslaufverlagerung"),
                    ("other", "Anderes Naturereignis"),
                ],
                max_length=24,
            ),
        ),
        migrations.RunPython(add_catalogues, remove_catalogues),
    ]
