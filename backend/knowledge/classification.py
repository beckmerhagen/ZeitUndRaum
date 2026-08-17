"""Vorsichtige, nachvollziehbare Inhaltsklassifikation für Explorationstreffer.

Die Kategorie beschreibt den Gegenstand einer Aussage. Sie ist ausdrücklich
nicht mit der Evidenz (Quelle/Fundstelle) und nicht mit einer historischen
Interpretation gleichzusetzen.
"""

import re
from collections import Counter

from .models import Entity


CATEGORY_KEYS = (
    "conflict",
    "natural_event",
    "political_event",
    "religious_event",
    "cultural_event",
    "event",
    "artwork",
    "building",
    "person",
    "organization",
    "movement",
    "place",
    "other",
)


INSTANCE_CATEGORIES = {
    # Person
    "Q5": "person",
    # Bildende Kunst / Werk
    "Q3305213": "artwork",  # painting
    "Q838948": "artwork",  # work of art
    "Q860861": "artwork",  # sculpture
    "Q4502142": "artwork",  # visual artwork
    # Bauwerk / architektonisches Objekt
    "Q41176": "building",
    "Q811979": "building",
    "Q4989906": "building",
    # Konflikt / Naturereignis
    "Q178561": "conflict",  # battle
    "Q198": "conflict",  # war
    "Q188055": "conflict",  # siege
    "Q8065": "natural_event",  # natural disaster
    "Q3839081": "natural_event",  # disaster
}


TEXT_PATTERNS = (
    (
        "conflict",
        # Do not use bare English ``war`` in this multilingual fallback. In
        # German it is the very common past tense of ``sein`` and otherwise
        # turns sentences such as "Dithmarschen war eine Region ..." into a
        # conflict. Explicit conflict terms and Wikidata instance types still
        # identify actual wars without that ambiguity.
        r"\b(krieg|guerre|battle|schlacht|bataille|siege|belagerung|siège|"
        r"armed conflict|bewaffneter konflikt|conflit armé|invasion|uprising|aufstand)\b",
    ),
    (
        "natural_event",
        r"\b(flood|hochwasser|überschwemmung|inondation|storm surge|sturmflut|"
        r"volcanic eruption|vulkanausbruch|éruption|earthquake|erdbeben|séisme|"
        r"tsunami|seebebenwelle|raz de marée|"
        r"drought|dürre|sécheresse|heatwave|hitzewelle|canicule|frost|kältewelle)\b",
    ),
    (
        "artwork",
        r"\b(painting|gemälde|peinture|portrait|porträt|sculpture|skulptur|"
        r"fresco|fresko|artwork|kunstwerk|œuvre d.art)\b",
    ),
    (
        "religious_event",
        r"\b(conclave|konklave|papal election|papstwahl|élection pontificale|"
        r"synod|synode|council|konzil|concile|canonization|heiligsprechung)\b",
    ),
    (
        "political_event",
        r"\b(election|wahl|élection|coronation|krönung|couronnement|treaty|vertrag|traité|"
        r"revolution|révolution|accession|independence|unabhängigkeit|indépendance)\b",
    ),
    (
        "cultural_event",
        r"\b(exhibition|ausstellung|exposition|festival|premiere|uraufführung|"
        r"publication|veröffentlichung|publication)\b",
    ),
    (
        "event",
        r"\b(historical.event|historical event|historisches ereignis|event|ereignis|événement)\b",
    ),
    (
        "building",
        r"\b(building|bauwerk|bâtiment|church|kirche|église|cathedral|kathedrale|cathédrale|"
        r"palace|palast|palais|castle|schloss|château|gate|tor|porte|bridge|brücke|pont|"
        r"fort|fortress|festung|mosque|moschee|mosquée|temple|stupa|monastery|kloster|monastère)\b",
    ),
    (
        "organization",
        r"\b(organization|organisation|university|universität|université|academy|akademie|académie|"
        r"museum|musée|musee|company|unternehmen|institution)\b",
    ),
    (
        "place",
        r"\b(city|stadt|ville|town|village|dorf|gemeinde|municipality|municipalité|"
        r"settlement|siedlung|locality|ort|district|bezirk|province|region|country|land|pays)\b",
    ),
)


KIND_CATEGORIES = {
    Entity.Kind.PLACE: "place",
    Entity.Kind.BUILDING: "building",
    Entity.Kind.PERSON: "person",
    Entity.Kind.ORGANIZATION: "organization",
    Entity.Kind.POLITY: "place",
    Entity.Kind.EVENT: "event",
    Entity.Kind.MOVEMENT: "movement",
    Entity.Kind.NATURAL_FEATURE: "place",
}


def _instance_ids(assertion):
    values = assertion.metadata.get("wikidata_instance_ids", [])
    if isinstance(values, str):
        values = values.split("|")
    return {str(value).rsplit("/", 1)[-1] for value in values}


def classify_assertion(assertion):
    """Return a presentation category and the basis used to derive it."""

    for qid in _instance_ids(assertion):
        if qid in INSTANCE_CATEGORIES:
            return {"key": INSTANCE_CATEGORIES[qid], "basis": "wikidata_instance"}

    text_parts = [assertion.subject.canonical_name, assertion.value_text, assertion.predicate]
    text_parts.extend(assertion.subject.labels.values())
    text_parts.extend(assertion.subject.descriptions.values())
    text = " ".join(str(part) for part in text_parts if part).casefold()
    for key, pattern in TEXT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return {"key": key, "basis": "description"}

    category = KIND_CATEGORIES.get(assertion.subject.kind, "other")
    return {"key": category, "basis": "entity_kind" if category != "other" else "fallback"}


def category_summary(assertions):
    classified = [(assertion, classify_assertion(assertion)) for assertion in assertions]
    counts = Counter(item["key"] for _, item in classified)
    return classified, [
        {"key": key, "count": counts[key]}
        for key in CATEGORY_KEYS
        if counts[key]
    ]


def time_world_patterns(classified):
    """Describe corpus patterns without turning simultaneity into causality."""

    by_category = {}
    for assertion, category in classified:
        by_category.setdefault(category["key"], []).append(assertion)

    patterns = []
    conflicts = by_category.get("conflict", [])
    if len(conflicts) >= 2:
        patterns.append(
            {
                "key": "conflict_cluster",
                "category": "conflict",
                "evidence_level": "algorithmic_similarity",
                "support_count": len(conflicts),
                "supporting_assertion_ids": [str(item.id) for item in conflicts[:24]],
                "confidence": 0.55,
                "limitation": "category_and_time_only",
            }
        )
        patterns.append(
            {
                "key": "religious_conflict_question",
                "category": "conflict",
                "evidence_level": "coincidence",
                "support_count": len(conflicts),
                "supporting_assertion_ids": [str(item.id) for item in conflicts[:24]],
                "confidence": 0.25,
                "limitation": "participants_and_motives_not_verified",
            }
        )

    ranked = sorted(by_category.items(), key=lambda item: (-len(item[1]), item[0]))
    if ranked and len(ranked[0][1]) >= 3:
        key, items = ranked[0]
        patterns.insert(
            0,
            {
                "key": "category_concentration",
                "category": key,
                "evidence_level": "algorithmic_similarity",
                "support_count": len(items),
                "supporting_assertion_ids": [str(item.id) for item in items[:24]],
                "confidence": 0.5,
                "limitation": "corpus_selection_bias",
            },
        )
    return patterns
