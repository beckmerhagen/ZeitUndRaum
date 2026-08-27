"""Kleine, nachvollziehbare Adapter für die öffentlichen Wikimedia-APIs."""

import html
import math
import re
import time
from urllib.parse import quote
from html.parser import HTMLParser

import requests
from django.conf import settings
from django.utils.html import strip_tags


EVENT_WORD_PATTERNS = {
    "de": re.compile(
        r"(?<!\w)(?:krieg|kriege|revolution|revolutionen|schlacht|belagerung|"
        r"aufstand|konflikt)(?!\w)",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"(?<!\w)(?:war|wars|revolution|revolutionary|battle|siege|uprising|conflict)(?!\w)",
        re.IGNORECASE,
    ),
    "fr": re.compile(
        r"(?<!\w)(?:guerre|guerres|révolution|revolution|bataille|siège|siege|"
        r"soulèvement|soulevement|conflit)(?!\w)",
        re.IGNORECASE,
    ),
}
YEAR_RANGE_PATTERN = re.compile(
    r"(?<!\d)(-?\d{3,4})\s*(?:bis|–|—|-|to)\s*(-?\d{3,4})(?!\d)",
    re.IGNORECASE,
)
HISTORY_SECTION_PATTERN = re.compile(
    r"^(?:history|geschichte|histoire|storja)(?:\b|\s|$)",
    re.IGNORECASE,
)
PORTAL_DIRECTORY_TITLES = {
    "de": "Wikipedia:WikiProjekt Portale/A-Z",
    "en": "Wikipedia:Contents/Portals",
    "fr": "Portail:Accueil",
}


class WikipediaSectionTextParser(HTMLParser):
    """Extrahiert Fließtext, aber keine Fußnoten, Tabellen oder Bildlegenden."""

    BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "br"}
    ALWAYS_SKIPPED = {"style", "script", "table", "sup", "figure", "nav"}
    SKIPPED_CLASSES = {
        "reflist",
        "references",
        "mw-references-wrap",
        "navbox",
        "hatnote",
        "thumb",
        "sidebar",
        "metadata",
    }
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if self.skip_depth:
            if tag not in self.VOID_TAGS:
                self.skip_depth += 1
            return
        classes = set(dict(attrs).get("class", "").casefold().split())
        if tag in self.ALWAYS_SKIPPED or classes.intersection(self.SKIPPED_CLASSES):
            if tag not in self.VOID_TAGS:
                self.skip_depth = 1
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append(". ")

    def handle_startendtag(self, tag, attrs):
        if not self.skip_depth and tag.casefold() in self.BLOCK_TAGS:
            self.parts.append(". ")

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag.casefold() in self.BLOCK_TAGS:
            self.parts.append(". ")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        return "".join(self.parts)


def wikipedia_request(language, parameters, *, attempts=3):
    for attempt in range(attempts):
        response = requests.get(
            f"https://{language}.wikipedia.org/w/api.php",
            params={"action": "query", "format": "json", **parameters},
            headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/json"},
            timeout=30,
        )
        if response.status_code not in (429, 503) or attempt == attempts - 1:
            response.raise_for_status()
            return response.json()
        retry_after = response.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 2**attempt
        time.sleep(min(delay, 16))


def wikipedia_page_url(language, title):
    return f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe=':_()')}"


def wikipedia_portal_pages(language, *, limit=None, top_level_only=True):
    """Liest das kuratierte Portalverzeichnis einer Sprachversion paginiert."""

    results = []
    seen = set()
    continuation = {}
    directory_title = PORTAL_DIRECTORY_TITLES.get(language, "Wikipedia:Contents/Portals")
    while True:
        payload = wikipedia_request(
            language,
            {
                "titles": directory_title,
                "prop": "links",
                "plnamespace": "100",
                "pllimit": "max",
                "maxlag": "5",
                **continuation,
            },
            attempts=5,
        )
        pages = payload.get("query", {}).get("pages", {})
        directory_page = next(iter(pages.values()), {}) if isinstance(pages, dict) else (pages[0] if pages else {})
        for page in directory_page.get("links", []):
            title = page.get("title", "")
            topic = title.split(":", 1)[-1]
            if not title or title in seen or (top_level_only and "/" in topic):
                continue
            seen.add(title)
            results.append({**page, "fullurl": wikipedia_page_url(language, title)})
            if limit and len(results) >= limit:
                return results
        continuation = payload.get("continue", {})
        if not continuation:
            return results
        time.sleep(0.1)


def wikipedia_portal_links(language, title, *, limit=250, continuation=None):
    """Liefert Artikellinks und den Revisionsstand eines Portals."""

    links = []
    seen = set()
    continuation = dict(continuation or {})
    revision_id = None
    while True:
        payload = wikipedia_request(
            language,
            {
                "titles": title,
                "prop": "links|info",
                "plnamespace": "0",
                "pllimit": str(min(500, max(1, limit - len(links)))) if limit else "max",
                "inprop": "url",
                "maxlag": "5",
                **continuation,
            },
            attempts=5,
        )
        pages = payload.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {}) if isinstance(pages, dict) else (pages[0] if pages else {})
        revision_id = page.get("lastrevid", revision_id)
        for item in page.get("links", []):
            article_title = item.get("title", "")
            if not article_title or article_title in seen:
                continue
            seen.add(article_title)
            links.append({**item, "fullurl": wikipedia_page_url(language, article_title)})
            if limit and len(links) >= limit:
                next_continuation = payload.get("continue", {})
                return {
                    "links": links,
                    "revision_id": revision_id,
                    "complete": not bool(next_continuation),
                    "continuation": next_continuation,
                }
        continuation = payload.get("continue", {})
        if not continuation:
            return {
                "links": links,
                "revision_id": revision_id,
                "complete": True,
                "continuation": {},
            }


def wikipedia_article_pages(language, titles):
    """Lädt belegbare Artikeldaten in API-sicheren Paketen."""

    results = []
    for offset in range(0, len(titles), 50):
        batch = titles[offset : offset + 50]
        payload = wikipedia_request(
            language,
            {
                "titles": "|".join(batch),
                "redirects": "1",
                "prop": "extracts|coordinates|pageimages|pageprops|info",
                "coprimary": "primary",
                "exintro": "1",
                "exsentences": "12",
                "explaintext": "1",
                "piprop": "thumbnail",
                "pithumbsize": "640",
                "inprop": "url",
                "maxlag": "5",
            },
            attempts=5,
        )
        pages = payload.get("query", {}).get("pages", {})
        values = pages.values() if isinstance(pages, dict) else pages
        results.extend(page for page in values if "missing" not in page)
        if offset + 50 < len(titles):
            time.sleep(1)
    return results


def wikipedia_history_section_page(language, page):
    """Lädt den eigentlichen Geschichtsabschnitt eines gewählten Ortsartikels.

    GeoSearch und Einleitung bleiben für die Umgebung zuständig. Der explizite
    Ortsartikel erhält zusätzlich genau einen transparent bezeichneten
    Geschichtsabschnitt, damit zentrale Ereignisse nicht hinter Sehenswürdigkeiten
    verschwinden.
    """

    title = page.get("title", "")
    if not title:
        return None
    sections_payload = wikipedia_request(
        language,
        {"action": "parse", "page": title, "prop": "sections"},
    )
    sections = sections_payload.get("parse", {}).get("sections", [])
    section = next(
        (
            item
            for item in sections
            if int(item.get("toclevel", 1)) == 1
            and HISTORY_SECTION_PATTERN.search(strip_tags(item.get("line", "")).strip())
        ),
        None,
    )
    if section is None:
        return None
    content_payload = wikipedia_request(
        language,
        {
            "action": "parse",
            "page": title,
            "prop": "text",
            "section": section["index"],
            "disableeditsection": "1",
        },
    )
    raw_html = content_payload.get("parse", {}).get("text", {}).get("*", "")
    if not raw_html:
        return None
    parser = WikipediaSectionTextParser()
    parser.feed(raw_html)
    extract = html.unescape(parser.text())
    extract = re.sub(r"\[(?:\d+|citation needed)\]", "", extract, flags=re.IGNORECASE)
    extract = re.sub(r"(?:\.\s*){2,}", ". ", extract)
    extract = " ".join(extract.split()).strip(" .")
    if not extract:
        return None
    history_page = dict(page)
    history_page["extract"] = extract
    history_page["_history_section"] = strip_tags(section.get("line", "")).strip()
    return history_page


def sorted_pages(payload):
    pages = payload.get("query", {}).get("pages", {})
    return sorted(pages.values(), key=lambda page: page.get("index", 9999))


def wikidata_entity(qid):
    response = requests.get(
        f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
        headers={"User-Agent": settings.WIKIMEDIA_USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("entities", {}).get(qid, {})


def wikidata_claim_year(entity, property_id):
    for statement in entity.get("claims", {}).get(property_id, []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        match = re.match(r"^([+-]?\d+)-", str(value.get("time", "")))
        if match:
            return int(match.group(1))
    return None


def wikidata_claim_coordinate(entity):
    """Return the preferred globe coordinate stored directly on an entity."""

    statements = entity.get("claims", {}).get("P625", [])
    preferred = [item for item in statements if item.get("rank") == "preferred"]
    for statement in [*preferred, *statements]:
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        latitude = value.get("latitude")
        longitude = value.get("longitude")
        if latitude is not None and longitude is not None:
            return {"lat": float(latitude), "lon": float(longitude)}
    return None


def extract_event_years(text, wikidata=None):
    wikidata = wikidata or {}
    start = wikidata_claim_year(wikidata, "P580") or wikidata_claim_year(wikidata, "P585")
    end = wikidata_claim_year(wikidata, "P582")
    if start is not None:
        return start, end or start
    match = YEAR_RANGE_PATTERN.search(text)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        return (start, end) if start <= end else (end, start)
    return None, None


def normalized_title(value):
    return " ".join(re.findall(r"\w+", (value or "").casefold()))


def describes_event(language, title, description):
    """Classify the entity itself, not events merely mentioned in its article.

    In particular, English ``war`` must not match the German verb ``war`` and a
    region must stay a place even when its introductory text mentions a war.
    """

    pattern = EVENT_WORD_PATTERNS.get(language, EVENT_WORD_PATTERNS["en"])
    return pattern.search(f"{title} {description}") is not None


def page_title_relevance(page, query):
    title = page.get("title", "")
    title_without_qualifier = re.sub(r"\s*\([^)]*\)\s*$", "", title)
    normalized_query = normalized_title(query)
    normalized_full_title = normalized_title(title)
    normalized_base_title = normalized_title(title_without_qualifier)
    if normalized_full_title == normalized_query or normalized_base_title == normalized_query:
        return 0
    if re.search(rf"(?<!\w){re.escape(normalized_query)}(?!\w)", normalized_full_title):
        return 1
    return 2


def page_distance_km(page, reference_center):
    coordinates = page.get("coordinates") or []
    if not coordinates or reference_center is None:
        return float("inf")
    coordinate = coordinates[0]
    latitude_1 = math.radians(float(reference_center.y))
    latitude_2 = math.radians(float(coordinate["lat"]))
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(float(coordinate["lon"]) - float(reference_center.x))
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(longitude_delta / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(haversine)))


def select_resolution_page(pages, query, reference_center=None):
    first_page = pages[0]
    is_disambiguation = "disambiguation" in first_page.get("pageprops", {})
    if not is_disambiguation:
        return first_page

    georeferenced = [page for page in pages if page.get("coordinates")]
    if not georeferenced:
        return first_page
    return min(
        georeferenced,
        key=lambda page: (
            page_title_relevance(page, query),
            page_distance_km(page, reference_center),
            page.get("index", 9999),
        ),
    )


def resolve_wikipedia_entity(query, languages, reference_center=None):
    """Bestimmt zuerst den eigentlichen Treffer und klassifiziert ihn erst danach.

    Wichtig: Ein Ereignis ohne Koordinate darf nie durch einen späteren, zufällig
    georeferenzierten Suchtreffer zu einem Ort werden.
    """

    for language in languages[:4]:
        payload = wikipedia_request(
            language,
            {
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": "0",
                "gsrlimit": "8",
                "prop": "coordinates|extracts|pageimages|pageprops|info",
                "coprimary": "primary",
                "exintro": "1",
                "exsentences": "5",
                "explaintext": "1",
                "piprop": "thumbnail",
                "pithumbsize": "640",
                "inprop": "url",
            },
        )
        pages = sorted_pages(payload)
        if not pages:
            continue
        page = select_resolution_page(pages, query, reference_center)
        qid = page.get("pageprops", {}).get("wikibase_item")
        wikidata = {}
        if qid:
            try:
                wikidata = wikidata_entity(qid)
            except requests.RequestException:
                # Wikipedia bleibt ein brauchbarer, transparent ausgewiesener Fallback.
                wikidata = {}
        title = page.get("title", query)
        description = (
            wikidata.get("descriptions", {}).get(language, {}).get("value")
            or wikidata.get("descriptions", {}).get("de", {}).get("value")
            or wikidata.get("descriptions", {}).get("en", {}).get("value")
            or page.get("pageprops", {}).get("wikibase-shortdesc", "")
        )
        extract = " ".join(page.get("extract", "").split())
        coordinates = page.get("coordinates") or []
        wikidata_coordinate = wikidata_claim_coordinate(wikidata)
        coordinate = coordinates[0] if coordinates else wikidata_coordinate
        start_year, end_year = extract_event_years(f"{description} {extract}", wikidata)
        event_words = describes_event(language, title, description)
        if event_words or (coordinate is None and start_year is not None and end_year is not None):
            kind = "event"
        elif coordinate:
            kind = "place"
        else:
            kind = "topic"
        return {
            "kind": kind,
            "language": language,
            "title": title,
            "qid": qid,
            "description": description or extract[:700],
            "extract": extract,
            "start_year": start_year,
            "end_year": end_year,
            "latitude": coordinate.get("lat") if coordinate else None,
            "longitude": coordinate.get("lon") if coordinate else None,
            "coordinate_source": "wikipedia" if coordinates else ("wikidata" if coordinate else None),
            "image_url": page.get("thumbnail", {}).get("source", ""),
            "page_url": page.get("fullurl", ""),
            "page": page,
        }
    return None


def resolve_wikipedia_place(query, languages, reference_center=None):
    """Löst einen Suchtext nur dann als Ort auf, wenn Wikipedia Koordinaten liefert."""
    resolved = resolve_wikipedia_entity(query, languages, reference_center=reference_center)
    return resolved if resolved and resolved["kind"] == "place" else None


def nearby_wikipedia_pages(language, center, radius_km, limit=24):
    """Lädt GeoSearch-Treffer mit stabiler Distanz und anschließend deren Metadaten."""

    nearby_payload = wikipedia_request(
        language,
        {
            "list": "geosearch",
            "gsprimary": "all",
            "gscoord": f"{center.y}|{center.x}",
            "gsradius": str(max(10, min(radius_km * 1000, 10000))),
            "gslimit": str(min(limit, 50)),
            "gsnamespace": "0",
        },
    )
    nearby = nearby_payload.get("query", {}).get("geosearch", [])
    if not nearby:
        return []

    page_ids = [str(item["pageid"]) for item in nearby]
    details_payload = wikipedia_request(
        language,
        {
            "pageids": "|".join(page_ids),
            "prop": "extracts|pageimages|pageprops|info",
            "exlimit": "max",
            # Einleitungsauszüge erlauben mehrere Seiten pro API-Aufruf.
            "exintro": "1",
            "exsentences": "10",
            "explaintext": "1",
            "piprop": "thumbnail",
            "pithumbsize": "320",
            "inprop": "url",
        },
    )
    details = details_payload.get("query", {}).get("pages", {})
    results = []
    for position, nearby_item in enumerate(nearby):
        page = details.get(str(nearby_item["pageid"]), {"pageid": nearby_item["pageid"], "title": nearby_item["title"]})
        page["index"] = position
        page["_coordinate"] = {"lat": nearby_item["lat"], "lon": nearby_item["lon"]}
        page["_distance_meters"] = nearby_item.get("dist", 0)
        results.append(page)
    return results


def linked_wikipedia_pages(language, event_title, limit=180):
    """Lädt georeferenzierte Hauptartikel, die ein Ereignisartikel direkt verknüpft."""

    links_payload = wikipedia_request(
        language,
        {
            "titles": event_title,
            "prop": "links",
            "plnamespace": "0",
            "pllimit": "max",
        },
    )
    link_titles = []
    for page in links_payload.get("query", {}).get("pages", {}).values():
        link_titles.extend(item["title"] for item in page.get("links", []) if item.get("title"))
    results = []
    for offset in range(0, min(len(link_titles), 500), 50):
        try:
            details_payload = wikipedia_request(
                language,
                {
                    "titles": "|".join(link_titles[offset : offset + 50]),
                    "prop": "coordinates|extracts|pageimages|pageprops|info",
                    "coprimary": "primary",
                    "exlimit": "max",
                    "exintro": "1",
                    "exsentences": "8",
                    "explaintext": "1",
                    "piprop": "thumbnail",
                    "pithumbsize": "320",
                    "inprop": "url",
                },
            )
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 429:
                # Bereits geladene Treffer bleiben nutzbar; ein späterer Lauf ergänzt den Rest.
                return results
            raise
        for page in details_payload.get("query", {}).get("pages", {}).values():
            coordinates = page.get("coordinates") or []
            if coordinates:
                page["_coordinate"] = {"lat": coordinates[0]["lat"], "lon": coordinates[0]["lon"]}
                results.append(page)
                if len(results) >= limit:
                    return results
        time.sleep(0.25)
    return results


def page_summary(page):
    short_description = page.get("pageprops", {}).get("wikibase-shortdesc", "").strip()
    if short_description:
        return short_description[:500]
    extract = " ".join(page.get("extract", "").split())
    if not extract:
        return "Georeferenzierter Wikipedia-Artikel in der Umgebung."
    first_sentence = extract.split(". ", 1)[0].rstrip(".") + "."
    return first_sentence[:700]
