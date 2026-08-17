import re
import unicodedata

from .models import EnvironmentalEvent


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


ENVIRONMENTAL_EVENT_ALIASES = {
    EnvironmentalEvent.Type.VOLCANO: {
        "vulkan",
        "vulkanausbruch",
        "vulkanausbruche",
        "volcano",
        "volcanoes",
        "volcanic eruption",
        "volcanic eruptions",
        "volcan",
        "volcans",
        "eruption volcanique",
        "eruptions volcaniques",
    },
    EnvironmentalEvent.Type.EARTHQUAKE: {
        "erdbeben",
        "earthquake",
        "earthquakes",
        "seisme",
        "seismes",
        "tremblement de terre",
        "tremblements de terre",
    },
    EnvironmentalEvent.Type.TSUNAMI: {
        "tsunami",
        "tsunamis",
        "seebebenwelle",
        "seebebenwellen",
        "raz de maree",
        "raz de maree tsunami",
    },
    EnvironmentalEvent.Type.STORM_SURGE: {
        "sturmflut",
        "sturmfluten",
        "storm surge",
        "storm surges",
        "onde de tempete",
        "ondes de tempete",
        "submersion marine",
        "submersions marines",
    },
    EnvironmentalEvent.Type.FLOOD: {
        "hochwasser",
        "uberschwemmung",
        "uberschwemmungen",
        "flood",
        "floods",
        "flooding",
        "inondation",
        "inondations",
        "crue",
        "crues",
    },
    EnvironmentalEvent.Type.DROUGHT: {
        "durre",
        "durren",
        "drought",
        "droughts",
        "secheresse",
        "secheresses",
    },
    EnvironmentalEvent.Type.HEATWAVE: {
        "hitzewelle",
        "hitzewellen",
        "heatwave",
        "heat wave",
        "heatwaves",
        "heat waves",
        "canicule",
        "canicules",
    },
    EnvironmentalEvent.Type.FROST: {
        "frost",
        "kalteperiode",
        "kalteperioden",
        "cold wave",
        "cold waves",
        "frost event",
        "frost events",
        "gel",
        "vague de froid",
        "vagues de froid",
    },
    EnvironmentalEvent.Type.RIVER_COURSE_CHANGE: {
        "flusslaufverlagerung",
        "flussbettverlagerung",
        "flussbett verlegt",
        "river course change",
        "river course changes",
        "deplacement du cours d eau",
        "deplacements du cours d eau",
    },
}

PLACE_LINK_WORDS = {
    "a",
    "am",
    "at",
    "bei",
    "de",
    "des",
    "du",
    "en",
    "in",
    "im",
    "near",
    "of",
    "um",
    "von",
}

UMBRELLA_ALIASES = {
    "naturereignis",
    "naturereignisse",
    "naturkatastrophe",
    "naturkatastrophen",
    "natural event",
    "natural events",
    "natural disaster",
    "natural disasters",
    "evenement naturel",
    "evenements naturels",
    "catastrophe naturelle",
    "catastrophes naturelles",
}


def parse_environmental_query(query):
    """Split a natural-event search into categories and an optional place.

    The parser deliberately does not infer a date. ``Sturmflut Hamburg`` and
    ``Hamburg Sturmflut`` therefore describe the same open-ended spatial
    catalogue search, while a bare ``Sturmflut`` keeps the global behaviour.
    """
    normalized = _normalize(query)
    if not normalized:
        return {"event_types": [], "place_query": ""}
    if normalized in UMBRELLA_ALIASES:
        return {"event_types": list(ENVIRONMENTAL_EVENT_ALIASES), "place_query": ""}

    matched = []
    remainder = f" {normalized} "
    aliases = sorted(
        (
            (_normalize(alias), event_type)
            for event_type, values in ENVIRONMENTAL_EVENT_ALIASES.items()
            for alias in values
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, event_type in aliases:
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        if re.search(pattern, remainder):
            remainder = re.sub(pattern, " ", remainder)
            if event_type not in matched:
                matched.append(event_type)

    if not matched:
        return {"event_types": [], "place_query": ""}

    words = [
        word
        for word in re.sub(r"\b(and|or|und|oder|et|ou)\b", " ", remainder).split()
        if word
    ]
    while words and words[0] in PLACE_LINK_WORDS:
        words.pop(0)
    while words and words[-1] in PLACE_LINK_WORDS:
        words.pop()
    return {"event_types": matched, "place_query": " ".join(words)}


def environmental_event_types_for_query(query):
    """Return keys only when the complete query denotes categories."""
    parsed = parse_environmental_query(query)
    return parsed["event_types"] if not parsed["place_query"] else []


def environmental_place_radius_km(resolved_place):
    """Choose an initial catalogue radius that matches the place granularity."""
    description = _normalize(resolved_place.get("description", ""))
    if re.search(r"\b(country|country in|staat|staat in|land in|pays|etat souverain)\b", description):
        return 1000
    if re.search(r"\b(region|district|county|kreis|province|bundesland|departement)\b", description):
        return 75
    return 50
