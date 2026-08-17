import csv
import io
import math
import zipfile
from calendar import monthrange
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
from django.conf import settings
from django.utils import timezone
from netCDF4 import Dataset


OWDA_SOURCE_URL = "https://www.ncei.noaa.gov/access/paleo-search/study/19419"
DWD_ANNUAL_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/annual/kl/historical"
DWD_STATIONS_URL = f"{DWD_ANNUAL_BASE}/KL_Jahreswerte_Beschreibung_Stationen.txt"
NASA_POWER_MONTHLY_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
NASA_POWER_DOCUMENTATION_URL = "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/"

ENVIRONMENT_MESSAGES = {
    "en": {
        "pdsi_extreme_dry": "extreme drought", "pdsi_severe_dry": "severe drought", "pdsi_moderate_dry": "moderate drought",
        "pdsi_extreme_wet": "extremely wet", "pdsi_very_wet": "very wet", "pdsi_unusual_wet": "unusually wet", "pdsi_normal": "within the range of ordinary fluctuations",
        "pdsi_title": "Summer moisture and drought", "pdsi_variable": "Reconstructed Palmer Drought Severity Index (PDSI)", "tree_reconstruction": "Tree-ring reconstruction", "grid_cell": "Grid cell", "grid_point": "Grid point {lat:.2f}° N, {lon:.2f}° E",
        "grid_resolution": "0.5° grid (about 33 × 56 km at this latitude)", "pdsi_reference": "PDSI 0 represents average moisture; negative values are drier and positive values wetter.", "no_focus_value": "no value for the focus year", "cite_dataset": "Cite the dataset; observe the source terms of use", "pdsi_uncertainty": "Annual tree-ring reconstruction, not an instrumental measurement. The grid cell represents the region, not the local microclimate.",
        "annual_temperature": "Annual mean temperature", "annual_precipitation": "Annual precipitation", "latest_year": "{year} (latest available year)", "instrumental": "Instrumental measurement", "weather_station": "Weather station", "station_point": "Point measurement at the weather station", "reference_mean": "Reference mean {period}: {value} {unit}", "focus_comparison": "{year}: {value} {unit}; difference from the reference mean {difference} {unit}", "ten_year_change": "Mean of the latest ten available years compared with the first ten: {change} {unit}", "dwd_provider": "German Weather Service · Climate Data Center", "station_uncertainty": "Station measurement. Relocations, instrument changes and missing years can affect comparability; the distance from the selected place is shown.",
        "power_reanalysis": "Global reanalysis", "power_grid": "NASA POWER grid cell", "power_grid_point": "MERRA-2 grid at {lat:.2f}° N, {lon:.2f}° E", "power_resolution": "MERRA-2 source grid 0.5° × 0.625°", "power_provider": "NASA POWER · MERRA-2", "power_license": "NASA data · citation requested", "power_uncertainty": "Spatial reanalysis, not a measurement at the selected place. The coarse grid can differ from local conditions, especially in mountains, cities and coastal areas.", "power_modern_reference": "Modern reference climate {period}; it does not describe conditions in the selected historical year.", "power_monthly_table": "Monthly climate table", "power_table_note": "Mean monthly temperature and precipitation for {period} from the MERRA-2 reanalysis.",
        "assessment_relations": "Verified or explicitly uncertain historical environmental links are available for this place.", "assessment_conditions": "Supraregional or local environmental conditions are recorded; a specific historical consequence at the selected place has not yet been verified.", "assessment_empty": "No matching environmental observations are available for this space–time selection yet. The source catalogue shows which collections can be evaluated next.", "causality": "Temporal coincidence is not causality. Historical consequences appear only through a separately evaluated EnvironmentalRelation.",
    },
    "de": {
        "pdsi_extreme_dry": "extreme Dürre", "pdsi_severe_dry": "starke Dürre", "pdsi_moderate_dry": "mäßige Dürre", "pdsi_extreme_wet": "extrem feucht", "pdsi_very_wet": "sehr feucht", "pdsi_unusual_wet": "ungewöhnlich feucht", "pdsi_normal": "im Bereich gewöhnlicher Schwankungen",
        "pdsi_title": "Sommerliche Feuchte und Dürre", "pdsi_variable": "Rekonstruierter Palmer-Dürreindex (PDSI)", "tree_reconstruction": "Rekonstruktion aus Baumringen", "grid_cell": "Rasterzelle", "grid_point": "Rasterpunkt {lat:.2f}° N, {lon:.2f}° E", "grid_resolution": "0,5° Raster (in dieser Breite etwa 33 × 56 km)", "pdsi_reference": "PDSI 0 bezeichnet durchschnittliche Feuchte; negative Werte sind trockener, positive feuchter.", "no_focus_value": "kein Wert für das Fokusjahr", "cite_dataset": "Datensatz zitieren; Nutzungsbedingungen der Quelle beachten", "pdsi_uncertainty": "Jährliche Rekonstruktion aus Baumringen, kein instrumenteller Messwert. Die Rasterzelle steht für die Region, nicht für das Mikroklima im Ort.",
        "annual_temperature": "Jahresmitteltemperatur", "annual_precipitation": "Jahresniederschlag", "latest_year": "{year} (jüngstes verfügbares Jahr)", "instrumental": "Instrumentelle Messung", "weather_station": "Wetterstation", "station_point": "Punktmessung an der Wetterstation", "reference_mean": "Vergleichsmittel {period}: {value} {unit}", "focus_comparison": "{year}: {value} {unit}; Abweichung vom Vergleichsmittel {difference} {unit}", "ten_year_change": "Mittel der letzten zehn verfügbaren Jahre gegenüber den ersten zehn: {change} {unit}", "dwd_provider": "Deutscher Wetterdienst · Climate Data Center", "station_uncertainty": "Stationsmessung. Verlegungen, Instrumentenwechsel und fehlende Jahre können die Vergleichbarkeit beeinflussen; die Entfernung zum gewählten Ort ist angegeben.",
        "power_reanalysis": "Globale Reanalyse", "power_grid": "NASA-POWER-Rasterzelle", "power_grid_point": "MERRA-2-Raster bei {lat:.2f}° N, {lon:.2f}° E", "power_resolution": "MERRA-2-Ausgangsraster 0,5° × 0,625°", "power_provider": "NASA POWER · MERRA-2", "power_license": "NASA-Daten · Quellenangabe erbeten", "power_uncertainty": "Räumliche Reanalyse, keine Messung am gewählten Ort. Das grobe Raster kann besonders im Gebirge, in Städten und an Küsten vom lokalen Klima abweichen.", "power_modern_reference": "Modernes Referenzklima {period}; es beschreibt nicht die Verhältnisse im gewählten historischen Jahr.", "power_monthly_table": "Monatliche Klimatabelle", "power_table_note": "Mittlere Monatstemperatur und Niederschlag für {period} aus der MERRA-2-Reanalyse.",
        "assessment_relations": "Für diesen Ort liegen belegte oder ausdrücklich als unsicher markierte historische Umweltbezüge vor.", "assessment_conditions": "Überregionale oder lokale Umweltbedingungen sind erfasst; eine konkrete historische Folge am gewählten Ort ist bislang nicht belegt.", "assessment_empty": "Für diesen Raum-Zeit-Ausschnitt liegen noch keine passenden Umweltbeobachtungen vor. Der Quellenkatalog zeigt, welche Bestände als Nächstes ausgewertet werden können.", "causality": "Zeitliches Zusammentreffen ist keine Kausalität. Historische Folgen erscheinen nur über eine eigene, bewertete EnvironmentalRelation.",
    },
    "fr": {
        "pdsi_extreme_dry": "sécheresse extrême", "pdsi_severe_dry": "forte sécheresse", "pdsi_moderate_dry": "sécheresse modérée", "pdsi_extreme_wet": "extrêmement humide", "pdsi_very_wet": "très humide", "pdsi_unusual_wet": "anormalement humide", "pdsi_normal": "dans la plage des fluctuations ordinaires",
        "pdsi_title": "Humidité estivale et sécheresse", "pdsi_variable": "Indice de sévérité de la sécheresse de Palmer reconstitué (PDSI)", "tree_reconstruction": "Reconstitution par les cernes des arbres", "grid_cell": "Maille", "grid_point": "Point de grille {lat:.2f}° N, {lon:.2f}° E", "grid_resolution": "Grille de 0,5° (environ 33 × 56 km à cette latitude)", "pdsi_reference": "Un PDSI de 0 représente une humidité moyenne ; les valeurs négatives sont plus sèches et les valeurs positives plus humides.", "no_focus_value": "aucune valeur pour l’année sélectionnée", "cite_dataset": "Citer le jeu de données et respecter les conditions d’utilisation de la source", "pdsi_uncertainty": "Reconstitution annuelle par les cernes des arbres, et non mesure instrumentale. La maille représente la région, pas le microclimat local.",
        "annual_temperature": "Température moyenne annuelle", "annual_precipitation": "Précipitations annuelles", "latest_year": "{year} (dernière année disponible)", "instrumental": "Mesure instrumentale", "weather_station": "Station météorologique", "station_point": "Mesure ponctuelle à la station météorologique", "reference_mean": "Moyenne de référence {period} : {value} {unit}", "focus_comparison": "{year} : {value} {unit} ; écart à la moyenne de référence {difference} {unit}", "ten_year_change": "Moyenne des dix dernières années disponibles par rapport aux dix premières : {change} {unit}", "dwd_provider": "Service météorologique allemand · Climate Data Center", "station_uncertainty": "Mesure en station. Les déplacements, changements d’instruments et années manquantes peuvent affecter la comparabilité ; la distance au lieu sélectionné est indiquée.",
        "power_reanalysis": "Réanalyse mondiale", "power_grid": "Maille NASA POWER", "power_grid_point": "Maille MERRA-2 à {lat:.2f}° N, {lon:.2f}° E", "power_resolution": "Grille source MERRA-2 de 0,5° × 0,625°", "power_provider": "NASA POWER · MERRA-2", "power_license": "Données NASA · citation demandée", "power_uncertainty": "Réanalyse spatiale, et non mesure au lieu sélectionné. La maille grossière peut différer du climat local, notamment en montagne, en ville et sur les côtes.", "power_modern_reference": "Climat de référence moderne {period} ; il ne décrit pas les conditions de l’année historique sélectionnée.", "power_monthly_table": "Tableau climatique mensuel", "power_table_note": "Température mensuelle moyenne et précipitations pour {period}, issues de la réanalyse MERRA-2.",
        "assessment_relations": "Des liens environnementaux historiques attestés ou explicitement incertains sont disponibles pour ce lieu.", "assessment_conditions": "Des conditions environnementales suprarégionales ou locales sont enregistrées ; aucune conséquence historique précise n’est encore attestée au lieu sélectionné.", "assessment_empty": "Aucune observation environnementale correspondante n’est encore disponible pour cette sélection spatio-temporelle. Le catalogue des sources indique les fonds à analyser ensuite.", "causality": "La coïncidence temporelle n’est pas une causalité. Les conséquences historiques n’apparaissent que par une EnvironmentalRelation évaluée séparément.",
    },
}


def environment_locale(exploration_context):
    primary = (exploration_context.languages or ["en"])[0].split("-")[0].lower()
    return primary if primary in ENVIRONMENT_MESSAGES else "en"


def environment_text(exploration_context, key, **values):
    return ENVIRONMENT_MESSAGES[environment_locale(exploration_context)][key].format(**values)


def environment_number(exploration_context, value, digits, signed=False):
    rendered = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return rendered.replace(".", ",") if environment_locale(exploration_context) in {"de", "fr"} else rendered


def haversine_km(latitude_a, longitude_a, latitude_b, longitude_b):
    radius = 6371.0088
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def graph_period(exploration_context, lower, upper):
    half_window = max(50, min(150, int(exploration_context.time_window_years) * 2))
    focus = int(exploration_context.time_focus_year)
    start = max(lower, focus - half_window)
    end = min(upper, focus + half_window)
    if start > end:
        return None
    return start, end


def pdsi_interpretation(value, exploration_context):
    if value <= -4:
        return environment_text(exploration_context, "pdsi_extreme_dry")
    if value <= -3:
        return environment_text(exploration_context, "pdsi_severe_dry")
    if value <= -2:
        return environment_text(exploration_context, "pdsi_moderate_dry")
    if value >= 4:
        return environment_text(exploration_context, "pdsi_extreme_wet")
    if value >= 3:
        return environment_text(exploration_context, "pdsi_very_wet")
    if value >= 2:
        return environment_text(exploration_context, "pdsi_unusual_wet")
    return environment_text(exploration_context, "pdsi_normal")


def owda_path():
    configured = Path(settings.OWDA_NETCDF_PATH)
    production_path = Path("/srv/explore/data/environment/owda.nc")
    return next((path for path in (configured, production_path) if path.is_file()), None)


def read_owda_point(variable, dimensions, lat_index, lon_index):
    indices = []
    for dimension in dimensions:
        if dimension == "lat":
            indices.append(lat_index)
        elif dimension == "lon":
            indices.append(lon_index)
        else:
            indices.append(slice(None))
    return np.ma.asarray(variable[tuple(indices)]).reshape(-1)


def owda_series(exploration_context):
    focus_year = int(exploration_context.time_focus_year)
    if not 0 <= focus_year <= 2012:
        return None
    path = owda_path()
    period = graph_period(exploration_context, 0, 2012)
    if not path or not period:
        return None

    with Dataset(path, "r") as dataset:
        latitudes = np.asarray(dataset.variables["lat"][:], dtype=float)
        longitudes = np.asarray(dataset.variables["lon"][:], dtype=float)
        years = np.asarray(dataset.variables["time"][:], dtype=int)
        variable = dataset.variables["pdsi"]
        lat_order = np.argsort(np.abs(latitudes - exploration_context.center.y))[:9]
        lon_order = np.argsort(np.abs(longitudes - exploration_context.center.x))[:9]
        candidates = sorted(
            (
                haversine_km(
                    exploration_context.center.y,
                    exploration_context.center.x,
                    float(latitudes[lat_index]),
                    float(longitudes[lon_index]),
                ),
                int(lat_index),
                int(lon_index),
            )
            for lat_index in lat_order
            for lon_index in lon_order
        )
        values = None
        grid_distance = None
        grid_latitude = None
        grid_longitude = None
        for distance, lat_index, lon_index in candidates:
            candidate = read_owda_point(variable, variable.dimensions, lat_index, lon_index)
            if np.ma.count(candidate) >= max(20, int(len(candidate) * 0.5)):
                values = candidate
                grid_distance = distance
                grid_latitude = float(latitudes[lat_index])
                grid_longitude = float(longitudes[lon_index])
                break
        if values is None:
            return None

        start, end = period
        points = []
        for year, value in zip(years, values, strict=True):
            if start <= int(year) <= end and not np.ma.is_masked(value) and float(value) < 100:
                points.append({"year": int(year), "value": round(float(value), 3)})
        if not points:
            return None

    focus_point = next((point for point in points if point["year"] == focus_year), None)
    return {
        "id": "owda-pdsi",
        "title": environment_text(exploration_context, "pdsi_title"),
        "variable": environment_text(exploration_context, "pdsi_variable"),
        "unit": "PDSI",
        "method": "reconstruction",
        "method_label": environment_text(exploration_context, "tree_reconstruction"),
        "spatial_scope": environment_text(exploration_context, "grid_cell"),
        "location_label": environment_text(exploration_context, "grid_point", lat=grid_latitude, lon=grid_longitude),
        "distance_km": round(grid_distance, 1),
        "spatial_resolution": environment_text(exploration_context, "grid_resolution"),
        "reference_label": environment_text(exploration_context, "pdsi_reference"),
        "baseline": 0,
        "focus_year": focus_year,
        "focus_point": focus_point,
        "focus_interpretation": pdsi_interpretation(focus_point["value"], exploration_context) if focus_point else environment_text(exploration_context, "no_focus_value"),
        "points": points,
        "source": {
            "provider": "NOAA/NCEI · Old World Drought Atlas",
            "url": OWDA_SOURCE_URL,
            "license": environment_text(exploration_context, "cite_dataset"),
        },
        "uncertainty": environment_text(exploration_context, "pdsi_uncertainty"),
    }


def parse_dwd_stations(text):
    stations = []
    for line in text.splitlines():
        if len(line) < 62 or not line[:5].isdigit():
            continue
        try:
            stations.append(
                {
                    "id": line[0:5],
                    "start_year": int(line[6:10]),
                    "end_year": int(line[15:19]),
                    "latitude": float(line[40:52]),
                    "longitude": float(line[52:61]),
                    "name": line[61:102].strip(),
                    "state": line[102:143].strip(),
                    "start_date": line[6:14],
                    "end_date": line[15:23],
                }
            )
        except ValueError:
            continue
    return stations


@lru_cache(maxsize=1)
def dwd_stations():
    response = requests.get(
        DWD_STATIONS_URL,
        timeout=20,
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT},
    )
    response.raise_for_status()
    return parse_dwd_stations(response.content.decode("latin1"))


def choose_dwd_station(exploration_context, start, end):
    candidates = []
    for station in dwd_stations():
        distance = haversine_km(
            exploration_context.center.y,
            exploration_context.center.x,
            station["latitude"],
            station["longitude"],
        )
        overlap = max(0, min(end, station["end_year"]) - max(start, station["start_year"]) + 1)
        missing = max(0, end - start + 1 - overlap)
        total_years = station["end_year"] - station["start_year"] + 1
        if distance <= 150 and overlap >= 10 and total_years >= 20:
            candidates.append((distance + missing * 2, distance, station))
    return min(candidates, default=(None, None, None), key=lambda item: item[0])[1:]


@lru_cache(maxsize=64)
def dwd_annual_rows(station_id, start_date, end_date):
    url = f"{DWD_ANNUAL_BASE}/jahreswerte_KL_{station_id}_{start_date}_{end_date}_hist.zip"
    response = requests.get(url, timeout=20, headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT})
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        product_name = next(name for name in archive.namelist() if name.startswith("produkt_"))
        content = archive.read(product_name).decode("latin1")
    rows = []
    for row in csv.DictReader(io.StringIO(content), delimiter=";"):
        cleaned = {key.strip(): value.strip() for key, value in row.items() if key}
        rows.append(cleaned)
    return url, rows


def numeric_dwd_value(row, key):
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return None if value <= -900 else value


def mean(values):
    return sum(values) / len(values) if values else None


def power_value(values, year, month):
    value = values.get(f"{year:04d}{month:02d}")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value <= -900 else value


@lru_cache(maxsize=256)
def nasa_power_monthly(latitude, longitude, end_year):
    response = requests.get(
        NASA_POWER_MONTHLY_URL,
        params={
            "parameters": "T2M,PRECTOTCORR",
            "community": "SB",
            "longitude": longitude,
            "latitude": latitude,
            "format": "JSON",
            "start": 1981,
            "end": end_year,
        },
        timeout=25,
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def nasa_power_series(exploration_context):
    if not getattr(settings, "NASA_POWER_ENABLED", True):
        return []
    end_year = timezone.now().year - 1
    latitude = round(float(exploration_context.center.y), 3)
    longitude = round(float(exploration_context.center.x), 3)
    payload = nasa_power_monthly(latitude, longitude, end_year)
    parameters = payload["properties"]["parameter"]
    temperatures = parameters["T2M"]
    precipitation_rates = parameters["PRECTOTCORR"]
    baseline_start = 1991 if end_year >= 2020 else 1981
    baseline_end = min(2020, end_year)
    baseline_period = f"{baseline_start}–{baseline_end}"

    monthly_rows = []
    for month in range(1, 13):
        monthly_temperatures = []
        monthly_precipitation = []
        for year in range(baseline_start, baseline_end + 1):
            temperature = power_value(temperatures, year, month)
            precipitation_rate = power_value(precipitation_rates, year, month)
            if temperature is not None:
                monthly_temperatures.append(temperature)
            if precipitation_rate is not None:
                monthly_precipitation.append(precipitation_rate * monthrange(year, month)[1])
        if monthly_temperatures and monthly_precipitation:
            monthly_rows.append(
                {
                    "month": month,
                    "temperature": round(mean(monthly_temperatures), 1),
                    "precipitation": round(mean(monthly_precipitation)),
                }
            )
    if len(monthly_rows) != 12:
        return []

    temperature_points = []
    precipitation_points = []
    for year in range(1981, end_year + 1):
        annual_temperature = power_value(temperatures, year, 13)
        monthly_totals = []
        for month in range(1, 13):
            rate = power_value(precipitation_rates, year, month)
            if rate is not None:
                monthly_totals.append(rate * monthrange(year, month)[1])
        if annual_temperature is not None:
            temperature_points.append({"year": year, "value": round(annual_temperature, 1)})
        if len(monthly_totals) == 12:
            precipitation_points.append({"year": year, "value": round(sum(monthly_totals))})
    if len(temperature_points) < 20 or len(precipitation_points) < 20:
        return []

    geometry = payload.get("geometry", {}).get("coordinates", [longitude, latitude])
    grid_longitude = float(geometry[0])
    grid_latitude = float(geometry[1])
    grid_distance = haversine_km(latitude, longitude, grid_latitude, grid_longitude)
    focus_year = int(exploration_context.time_focus_year)
    outside_data_period = focus_year < 1981 or focus_year > end_year
    source = {
        "provider": environment_text(exploration_context, "power_provider"),
        "url": NASA_POWER_DOCUMENTATION_URL,
        "license": environment_text(exploration_context, "power_license"),
    }
    table = {
        "id": "nasa-power-monthly-normal",
        "title": environment_text(exploration_context, "power_monthly_table"),
        "period": baseline_period,
        "note": environment_text(exploration_context, "power_table_note", period=baseline_period),
        "temperature_unit": "°C",
        "precipitation_unit": "mm",
        "rows": monthly_rows,
        "source": source,
    }

    output = []
    for identifier, title, unit, digits, points in (
        ("nasa-power-temperature", environment_text(exploration_context, "annual_temperature"), "°C", 1, temperature_points),
        ("nasa-power-precipitation", environment_text(exploration_context, "annual_precipitation"), "mm", 0, precipitation_points),
    ):
        baseline_values = [
            point["value"] for point in points if baseline_start <= point["year"] <= baseline_end
        ]
        baseline = mean(baseline_values)
        exact_focus = next((point for point in points if point["year"] == focus_year), None)
        focus_point = exact_focus or points[-1]
        first_mean = mean([point["value"] for point in points[:10]])
        last_mean = mean([point["value"] for point in points[-10:]])
        if outside_data_period:
            focus_interpretation = environment_text(
                exploration_context,
                "power_modern_reference",
                period=baseline_period,
            )
        else:
            focus_interpretation = environment_text(
                exploration_context,
                "focus_comparison",
                year=focus_year,
                value=environment_number(exploration_context, focus_point["value"], digits),
                difference=environment_number(
                    exploration_context,
                    focus_point["value"] - baseline,
                    digits,
                    signed=True,
                ),
                unit=unit,
            )
        item = {
            "id": identifier,
            "title": title,
            "variable": title,
            "unit": unit,
            "method": "reanalysis",
            "method_label": environment_text(exploration_context, "power_reanalysis"),
            "spatial_scope": environment_text(exploration_context, "power_grid"),
            "location_label": environment_text(
                exploration_context,
                "power_grid_point",
                lat=grid_latitude,
                lon=grid_longitude,
            ),
            "distance_km": round(grid_distance, 1),
            "spatial_resolution": environment_text(exploration_context, "power_resolution"),
            "reference_label": environment_text(
                exploration_context,
                "reference_mean",
                period=baseline_period,
                value=environment_number(exploration_context, baseline, digits),
                unit=unit,
            ),
            "baseline": round(baseline, digits + 1),
            "focus_year": focus_year,
            "focus_point": focus_point,
            "focus_interpretation": focus_interpretation,
            "change_summary": environment_text(
                exploration_context,
                "ten_year_change",
                change=environment_number(exploration_context, last_mean - first_mean, digits, signed=True),
                unit=unit,
            ),
            "points": points,
            "source": source,
            "uncertainty": environment_text(exploration_context, "power_uncertainty"),
        }
        if identifier == "nasa-power-temperature":
            item["monthly_table"] = table
        output.append(item)
    return output


def measurement_series(exploration_context):
    period = graph_period(exploration_context, 1881, 2025)
    if not period:
        return []
    start, end = period
    distance, station = choose_dwd_station(exploration_context, start, end)
    if not station:
        return []
    source_url, rows = dwd_annual_rows(station["id"], station["start_date"], station["end_date"])
    definitions = [
        ("dwd-temperature", environment_text(exploration_context, "annual_temperature"), "JA_TT", "°C", 1),
        ("dwd-precipitation", environment_text(exploration_context, "annual_precipitation"), "JA_RR", "mm", 0),
    ]
    output = []
    focus_year = int(exploration_context.time_focus_year)
    for identifier, title, field, unit, digits in definitions:
        all_points = []
        for row in rows:
            value = numeric_dwd_value(row, field)
            if value is None:
                continue
            year = int(row["MESS_DATUM_BEGINN"][:4])
            if start <= year <= end:
                all_points.append({"year": year, "value": round(value, digits)})
        if len(all_points) < 10:
            continue
        baseline_values = [
            point["value"] for point in all_points if 1961 <= point["year"] <= 1990
        ]
        baseline_period = "1961–1990"
        if len(baseline_values) < 20:
            baseline_values = [point["value"] for point in all_points[: min(30, len(all_points))]]
            baseline_period = f"{all_points[0]['year']}–{all_points[min(29, len(all_points) - 1)]['year']}"
        baseline = mean(baseline_values)
        focus_point = next((point for point in all_points if point["year"] == focus_year), None)
        if focus_point is None and focus_year > all_points[-1]["year"]:
            focus_point = all_points[-1]
        focus_year_label = (
            str(focus_point["year"])
            if focus_point and focus_point["year"] == focus_year
            else environment_text(exploration_context, "latest_year", year=focus_point["year"]) if focus_point else ""
        )
        first_mean = mean([point["value"] for point in all_points[:10]])
        last_mean = mean([point["value"] for point in all_points[-10:]])
        change = last_mean - first_mean
        output.append(
            {
                "id": identifier,
                "title": title,
                "variable": title,
                "unit": unit,
                "method": "measurement",
                "method_label": environment_text(exploration_context, "instrumental"),
                "spatial_scope": environment_text(exploration_context, "weather_station"),
                "location_label": f"DWD-Station {station['name']} ({station['id']})",
                "distance_km": round(distance, 1),
                "spatial_resolution": environment_text(exploration_context, "station_point"),
                "reference_label": environment_text(
                    exploration_context,
                    "reference_mean",
                    period=baseline_period,
                    value=environment_number(exploration_context, baseline, digits),
                    unit=unit,
                ),
                "baseline": round(baseline, digits + 1),
                "focus_year": focus_year,
                "focus_point": focus_point,
                "focus_interpretation": (
                    environment_text(
                        exploration_context,
                        "focus_comparison",
                        year=focus_year_label,
                        value=environment_number(exploration_context, focus_point["value"], digits),
                        difference=environment_number(exploration_context, focus_point["value"] - baseline, digits, signed=True),
                        unit=unit,
                    )
                    if focus_point
                    else environment_text(exploration_context, "no_focus_value")
                ),
                "change_summary": environment_text(
                    exploration_context,
                    "ten_year_change",
                    change=environment_number(exploration_context, change, digits, signed=True),
                    unit=unit,
                ),
                "points": all_points,
                "source": {
                    "provider": environment_text(exploration_context, "dwd_provider"),
                    "url": source_url,
                    "license": "CC BY 4.0",
                },
                "uncertainty": environment_text(exploration_context, "station_uncertainty"),
            }
        )
    return output


def build_climate_series(exploration_context):
    series = []
    warnings = []
    try:
        reconstruction = owda_series(exploration_context)
        if reconstruction:
            series.append(reconstruction)
    except (OSError, KeyError, ValueError) as error:
        warnings.append(f"OWDA konnte nicht gelesen werden: {error}")
    try:
        series.extend(measurement_series(exploration_context))
    except (requests.RequestException, zipfile.BadZipFile, KeyError, ValueError, StopIteration) as error:
        warnings.append(f"DWD konnte nicht gelesen werden: {error}")
    try:
        series.extend(nasa_power_series(exploration_context))
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        warnings.append(f"NASA POWER konnte nicht gelesen werden: {error}")
    return series, warnings
