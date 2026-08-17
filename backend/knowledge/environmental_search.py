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


def environmental_event_types_for_query(query):
    """Return event-type keys only when the complete query denotes categories."""
    normalized = _normalize(query)
    if not normalized:
        return []
    if normalized in UMBRELLA_ALIASES:
        return list(ENVIRONMENTAL_EVENT_ALIASES)

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

    # Accept lists such as "Erdbeben, Vulkanausbruch und Sturmflut", but do
    # not turn a concrete title like "Erdbeben von Lissabon" into a global
    # category search.
    filler = re.sub(r"\b(and|or|und|oder|et|ou)\b", " ", remainder)
    filler = re.sub(r"[^a-z0-9]+", "", filler)
    return matched if matched and not filler else []

