import { useCallback, useEffect, useRef, useState } from "react";
import { divIcon, latLng } from "leaflet";
import { Circle, MapContainer, Marker, Popup, TileLayer, useMapEvents } from "react-leaflet";
import {
  ApiError,
  createExplorationContext,
  loadEventDossier,
  loadEnvironmentalEvents,
  loadExplorationContext,
  loadExplorationResults,
  loadExplorationTimeline,
  loadHistoricalProcesses,
  loadLivingConditions,
  loadKnowledgeBounds,
  loadResearch,
  loadTimeWorld,
  resolveExplorationInput,
  reverseGeocodePlace,
  startExplorationResearch,
  updateExplorationContext,
} from "./api";
import { coverageLabel, formatNumber, preferredLanguages, t, uiLocale, yearLabel } from "./i18n";

const CONTEXT_STORAGE_KEY = "zeitundraum.explorationContext";
const FALLBACK_LANGUAGES = preferredLanguages();

const DEFAULT_CONTEXT = {
  place_name: "Krempe",
  latitude: 53.836,
  longitude: 9.489,
  map_zoom: 11,
  time_focus_year: 1814,
  time_window_years: 0,
  time_unbounded: false,
  radius_km: 25,
  space_unbounded: false,
  query: "",
  query_mode: "auto",
  anchor_mode: "space",
  topics: [],
  perspectives: [],
  languages: FALLBACK_LANGUAGES,
  include_candidates: true,
  environmental_event_types: [],
  environmental_place_name: "",
};

const FOCUS_AXIS_STEPS = 10000;
const FOCUS_LOG_CURVE = 99;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function toLogAxisPosition(value, minimum, maximum) {
  if (maximum <= minimum) return 0;
  const normalized = clamp((value - minimum) / (maximum - minimum), 0, 1);
  return Math.log1p(FOCUS_LOG_CURVE * normalized) / Math.log1p(FOCUS_LOG_CURVE);
}

function fromLogAxisPosition(position, minimum, maximum) {
  if (maximum <= minimum) return minimum;
  const normalized = Math.expm1(clamp(position, 0, 1) * Math.log1p(FOCUS_LOG_CURVE)) / FOCUS_LOG_CURVE;
  return minimum + normalized * (maximum - minimum);
}

const RESEARCH_STATUS_LABELS = {
  queued: t("statusQueued"),
  running: t("statusRunning"),
  complete: t("statusComplete"),
  partial: t("statusPartial"),
  failed: t("statusFailed"),
};

const KNOWLEDGE_TYPE_KEYS = {
  documented: "knowledgeDocumented",
  reconstructed: "knowledgeReconstructed",
  scholarly_interpretation: "knowledgeScholarly",
  automatic_extraction: "knowledgeAutomatic",
};

const ASSERTION_RELATION_EVIDENCE_KEYS = {
  documented: "connectionDocumented",
  scholarly_plausible: "connectionPlausible",
  algorithmic_similarity: "connectionSimilarity",
  coincidence: "connectionCoincidence",
};

const CONTENT_CATEGORY_KEYS = {
  conflict: "categoryConflict",
  natural_event: "categoryNaturalEvent",
  political_event: "categoryPoliticalEvent",
  religious_event: "categoryReligiousEvent",
  cultural_event: "categoryCulturalEvent",
  event: "categoryEvent",
  artwork: "categoryArtwork",
  building: "categoryBuilding",
  person: "categoryPerson",
  organization: "categoryOrganization",
  movement: "categoryMovement",
  place: "categoryPlace",
  other: "categoryOther",
};

const PROCESS_TYPE_KEYS = {
  intellectual: "processIntellectual",
  political: "processPolitical",
  social: "processSocial",
  economic: "processEconomic",
  religious: "processReligious",
  cultural: "processCultural",
  environmental: "processEnvironmental",
  technological: "processTechnological",
  demographic: "processDemographic",
  other: "processOther",
};

const SPATIAL_CONTENT_CATEGORIES = new Set(["place", "building", "event", "conflict", "natural_event", "political_event", "religious_event", "cultural_event"]);

function categoryLabel(key) {
  return t(CONTENT_CATEGORY_KEYS[key] ?? "categoryOther");
}

function canEnterAssertionLocation(assertion) {
  return Boolean(assertion.location && SPATIAL_CONTENT_CATEGORIES.has(assertion.content_category?.key));
}

function assertionDate(assertion, end = false) {
  const year = assertion[end ? "time_end_year" : "time_start_year"];
  const month = assertion[end ? "time_end_month" : "time_start_month"];
  const day = assertion[end ? "time_end_day" : "time_start_day"];
  if (year == null) return null;
  if (month == null) return yearLabel(year);
  if (uiLocale === "en") return day == null ? `${month}/${yearLabel(year)}` : `${month}/${day}/${yearLabel(year)}`;
  return day == null ? `${month}.${yearLabel(year)}` : `${day}.${month}.${yearLabel(year)}`;
}

function preferredAssertionLink(assertion) {
  const source = assertion.evidence?.[0]?.source;
  return assertion.preferred_link || (source
    ? { provider: source.provider, url: source.url, kind: "source", language: source.language }
    : null);
}

function preferredAssertionLinkLabel(link) {
  if (!link) return "";
  if (link.kind === "wikipedia_resolver") return t("openWikipediaBestLanguage");
  if (link.kind?.startsWith("wikipedia")) return t("openWikipedia", { language: link.language });
  return `${link.provider}: ${t("openOriginal")}`;
}

const CATEGORY_MARKER_SYMBOLS = {
  conflict: "⚔",
  natural_event: "▲",
  political_event: "⚑",
  religious_event: "✦",
  cultural_event: "♫",
  event: "◆",
  artwork: "◈",
  building: "▥",
  person: "●",
  organization: "◎",
  movement: "↝",
  place: "⌖",
  other: "•",
};

const ENVIRONMENTAL_MARKER_SYMBOLS = {
  volcano: "▲",
  earthquake: "≋",
  tsunami: "≈",
  storm_surge: "≋",
  drought: "☀",
  heatwave: "☀",
  frost: "❄",
  flood: "≈",
  river_course_change: "↝",
  other: "◆",
};

function categoryMarkerIcon(category = "other", symbol = null) {
  const safeCategory = Object.hasOwn(CATEGORY_MARKER_SYMBOLS, category) ? category : "other";
  return divIcon({
    className: `map-category-marker ${safeCategory}`,
    html: `<span aria-hidden="true">${symbol ?? CATEGORY_MARKER_SYMBOLS[safeCategory]}</span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -14],
  });
}

function AssertionMapPopup({ assertion, onClose }) {
  const preferredLink = preferredAssertionLink(assertion);
  const date = assertionDate(assertion);
  return (
    <Popup
      className="map-marker-popup"
      autoPan
      keepInView
      closeButton={false}
      maxWidth={340}
      minWidth={220}
      autoPanPaddingTopLeft={[20, 138]}
      autoPanPaddingBottomRight={[20, 190]}
    >
      <div
        className="map-marker-card"
        onClick={onClose}
      >
        <span className="map-marker-meta">{date}{date && assertion.content_category?.key ? " · " : ""}{assertion.content_category?.key ? categoryLabel(assertion.content_category.key) : ""}</span>
        <strong>{assertion.subject.canonical_name}</strong>
        {assertion.value && <span className="map-marker-description">{assertion.value}</span>}
        {preferredLink && (
          <a
            className="map-marker-open"
            href={preferredLink.url}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            {preferredAssertionLinkLabel(preferredLink)}
          </a>
        )}
      </div>
    </Popup>
  );
}

function AssertionMapMarker({ assertion }) {
  const markerRef = useRef(null);
  const category = assertion.content_category?.key ?? "other";
  return (
    <Marker
      ref={markerRef}
      position={[assertion.location.latitude, assertion.location.longitude]}
      icon={categoryMarkerIcon(category)}
      eventHandlers={{
        mouseover: () => markerRef.current?.openPopup(),
      }}
    >
      <AssertionMapPopup
        assertion={assertion}
        onClose={(event) => {
          event?.preventDefault?.();
          event?.stopPropagation?.();
          markerRef.current?.closePopup();
        }}
      />
    </Marker>
  );
}

function contextIdFromUrl() {
  return new URLSearchParams(window.location.search).get("context") || window.localStorage.getItem(CONTEXT_STORAGE_KEY);
}

function rememberContext(id) {
  window.localStorage.setItem(CONTEXT_STORAGE_KEY, id);
  const url = new URL(window.location.href);
  url.searchParams.set("context", id);
  window.history.replaceState({}, "", url);
}

function mergeExploration(base, patch) {
  const merged = { ...base, ...patch };
  if (patch.latitude !== undefined || patch.longitude !== undefined) {
    merged.center = {
      latitude: patch.latitude ?? base.center.latitude,
      longitude: patch.longitude ?? base.center.longitude,
    };
  }
  return merged;
}

function worldOverviewZoom(map) {
  const width = Math.max(320, map.getSize().x);
  return Math.max(2.15, Math.min(4.5, Math.log2(width / 256) + 0.08));
}

function MapController({ exploration, eventPlaces, environmentalEvents, onPlaceChange, onZoomChange }) {
  const lastAutomaticViewRef = useRef("");
  const map = useMapEvents({
    click(event) {
      if (map._popup) {
        map.closePopup();
        return;
      }
      onPlaceChange({
        place_name: t("selectedPlace"),
        latitude: event.latlng.lat,
        longitude: event.latlng.lng,
      });
    },
    zoomend() {
      if (exploration.anchor_mode === "space" && map.getZoom() !== Number(exploration.map_zoom)) {
        onZoomChange(map.getZoom());
      }
    },
  });

  const automaticViewKey = exploration.anchor_mode === "time"
    ? `time:${exploration.time_focus_year}:${exploration.time_window_years}:${exploration.time_unbounded}:${exploration.space_unbounded}`
    : exploration.anchor_mode === "environment"
      ? `environment:${exploration.environmental_place_name}:${environmentalEvents.map((item) => item.id).join(",")}`
      : exploration.anchor_mode === "event"
        ? `event:${exploration.focus_entity?.external_id ?? exploration.focus_entity?.canonical_name ?? ""}:${eventPlaces.map((item) => item.id).join(",")}`
        : `space:${exploration.center.latitude}:${exploration.center.longitude}:${exploration.map_zoom}`;

  useEffect(() => {
    if (lastAutomaticViewRef.current === automaticViewKey) return;
    lastAutomaticViewRef.current = automaticViewKey;
    if (exploration.anchor_mode === "time") {
      if (exploration.space_unbounded) {
        map.flyTo([22, 12], worldOverviewZoom(map), { duration: 0.65 });
      } else {
        const focusBounds = latLng(
          exploration.center.latitude,
          exploration.center.longitude,
        ).toBounds(Math.max(1, Number(exploration.radius_km)) * 2000);
        map.fitBounds(focusBounds, {
          padding: [70, 70],
          maxZoom: 12,
          animate: true,
          duration: 0.65,
        });
      }
    } else if (exploration.anchor_mode === "environment") {
      const points = environmentalEvents.filter((item) => item.map_point);
      if (points.length > 1) {
        map.fitBounds(
          points.map((item) => [item.map_point.latitude, item.map_point.longitude]),
          { padding: [70, 70], maxZoom: 5, animate: true, duration: 0.65 },
        );
      } else if (points.length === 1) {
        map.flyTo([points[0].map_point.latitude, points[0].map_point.longitude], 5, { duration: 0.65 });
      } else {
        map.flyTo([22, 12], worldOverviewZoom(map), { duration: 0.65 });
      }
    } else if (exploration.anchor_mode === "event" && eventPlaces.length) {
      map.fitBounds(
        eventPlaces.map((item) => [item.location.latitude, item.location.longitude]),
        { padding: [70, 70], maxZoom: 6, animate: true, duration: 0.65 },
      );
    } else {
      map.flyTo(
        [exploration.center.latitude, exploration.center.longitude],
        Number(exploration.map_zoom),
        { duration: 0.55 },
      );
    }
  }, [automaticViewKey, environmentalEvents, eventPlaces, exploration.anchor_mode, exploration.center.latitude, exploration.center.longitude, exploration.map_zoom, exploration.radius_km, exploration.space_unbounded, map]);

  useEffect(() => {
    const fillWorldPanel = () => {
      map.invalidateSize({ pan: false });
      if (exploration.anchor_mode === "time" && exploration.space_unbounded) {
        map.setView([22, 12], worldOverviewZoom(map), { animate: false });
      }
    };
    map.on("resize", fillWorldPanel);
    return () => map.off("resize", fillWorldPanel);
  }, [exploration.anchor_mode, exploration.space_unbounded, map]);
  return null;
}

function AssertionCard({ assertion, onPlaceSelect }) {
  const preferredLink = preferredAssertionLink(assertion);
  const category = assertion.content_category?.key ?? "other";
  const startLabel = assertionDate(assertion);
  const endLabel = assertionDate(assertion, true);
  const statusLabel = assertion.status === "verified"
    ? t("verified")
    : assertion.status === "disputed" ? t("disputed") : t("automaticallyFound");
  return (
    <article className="fact-card">
      {assertion.image_url && <img className="fact-image" src={assertion.image_url} alt="" loading="lazy" />}
      <div className="fact-copy">
        <div className="fact-meta">
          <span><span className={`status ${assertion.status}`}>{statusLabel}</span> · {t(KNOWLEDGE_TYPE_KEYS[assertion.knowledge_type] ?? "knowledgeAutomatic")}</span>
          <span>{assertion.distance_km == null ? t("locationUncertain") : `${assertion.distance_km} km`}</span>
        </div>
        <span className={`content-category ${category}`}>{categoryLabel(category)}</span>
        <h3>{assertion.subject.canonical_name}</h3>
        <p>{assertion.value}</p>
        <div className="time-row">
          <strong>{startLabel ?? t("placeEntry")}</strong>
          {assertion.time_end_year != null && assertion.time_end_year !== assertion.time_start_year && (
            <span>{t("until")} {endLabel}</span>
          )}
          <span>{t("confidence")} {Math.round(Number(assertion.confidence) * 100)} %</span>
        </div>
        {preferredLink && (
          <a href={preferredLink.url} target="_blank" rel="noreferrer">
            {preferredAssertionLinkLabel(preferredLink)}
          </a>
        )}
        <details className="provenance">
          <summary>{t("provenanceUncertainty")}</summary>
          <p>{assertion.confidence_reason}</p>
          <dl>
            <div><dt>{t("temporalPrecision")}</dt><dd>{assertion.time_precision} · ±{assertion.temporal_uncertainty_years} {t("years")}</dd></div>
            <div><dt>{t("spatialPrecision")}</dt><dd>{assertion.spatial_precision_meters == null ? t("notSpecified") : `${formatNumber(assertion.spatial_precision_meters)} m`}</dd></div>
          </dl>
          {assertion.evidence.map((item) => (
            <div className="evidence-record" key={item.id}>
              <strong>{item.source.provider}: {item.source.title}</strong>
              <span>{t("locator")}: {item.locator}</span>
              <span>{t("license")}: {item.source.license_name}</span>
              <span>{t("retrieved")}: {new Date(item.source.retrieved_at).toLocaleDateString(uiLocale)}</span>
            </div>
          ))}
        </details>
        {onPlaceSelect && canEnterAssertionLocation(assertion) && (
          <button className="place-pivot" type="button" onClick={() => onPlaceSelect(assertion)}>
            {category.includes("event") || category === "conflict" ? t("enterScene") : t("enterPlace")}
          </button>
        )}
      </div>
    </article>
  );
}

function AssertionRelations({ relations }) {
  if (!relations?.length) return null;
  return (
    <section className="assertion-relations" aria-label={t("knowledgeConnections")}>
      <div className="section-heading"><h3>{t("knowledgeConnections")}</h3><span>{relations.length}</span></div>
      <p className="connection-note">{t("simultaneityWarning")}</p>
      {relations.map((relation) => (
        <article className={`connection-card ${relation.evidence_level}`} key={relation.id}>
          <div className="connection-level">{t(ASSERTION_RELATION_EVIDENCE_KEYS[relation.evidence_level] ?? "connectionCoincidence")}</div>
          <strong>{relation.source_assertion.subject.canonical_name} → {relation.target_assertion.subject.canonical_name}</strong>
          <p>{relation.summary}</p>
          <small>{t("confidence")} {Math.round(Number(relation.confidence) * 100)} % · {relation.confidence_reason}</small>
        </article>
      ))}
    </section>
  );
}

function PlaceTimeline({ timeline, onMomentSelect }) {
  const [visibleMomentCount, setVisibleMomentCount] = useState(100);
  const eventName = timeline?.filter?.type === "event" ? timeline.filter.name : "";
  const reference = timeline?.scope?.type === "place_history" ? timeline.reference_place : null;
  const moments = [...(timeline?.moments ?? [])].sort(
    (left, right) => right.year - left.year || (right.end_year ?? right.year) - (left.end_year ?? left.year),
  );
  useEffect(() => {
    setVisibleMomentCount(100);
  }, [timeline?.exploration_context?.id, timeline?.reference_place?.name]);
  return (
    <section className="pivot-section" aria-label={eventName ? t("eventTimeLinksAria", { event: eventName }) : t("placeTimesAria")}>
      {reference && (
        <div className="timeline-reference">
          <span>{t("timelineReference")}</span>
          <strong>{reference.name}</strong>
          <p>
            {formatNumber(reference.center.latitude, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}°, {" "}
            {formatNumber(reference.center.longitude, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}°
          </p>
          <small>{t("timelineLocalScope", {
            radius: timeline.scope.local_radius_km,
            explorationRadius: timeline.scope.exploration_radius_km,
          })}</small>
        </div>
      )}
      <div className="section-heading">
        <h3>{eventName ? t("eventLinks", { event: eventName }) : t("significantTimes")}</h3>
        <span>{timeline?.moment_count ?? 0} {t("moments")}</span>
      </div>
      {!moments.length ? (
        <p className="empty compact">
          {eventName
            ? t("noDatedEventLinks", { event: eventName })
            : t("noDatedStatements")}
        </p>
      ) : (
        <div className="timeline-list">
          {moments.slice(0, visibleMomentCount).map((moment) => {
          const lead = moment.assertions[0];
          const range = moment.end_year !== moment.year
            ? `${yearLabel(moment.year)}–${yearLabel(moment.end_year)}`
            : yearLabel(moment.year);
          return (
            <button
              className="timeline-moment"
              type="button"
              key={`${moment.year}:${moment.end_year}`}
              onClick={() => onMomentSelect(moment)}
            >
              <strong>{range}</strong>
              <span><b>{lead?.subject?.canonical_name}</b>{lead?.value ? ` · ${lead.value}` : ""}</span>
              <small>{moment.count} {t(moment.count === 1 ? "statement" : "statements")} · {t("travelToTime")}</small>
            </button>
          );
          })}
          {visibleMomentCount < moments.length && (
            <button
              className="timeline-more"
              type="button"
              onClick={() => setVisibleMomentCount((count) => count + 100)}
            >
              {t("showOlderTimes", { count: Math.min(100, moments.length - visibleMomentCount) })}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function TimeWorld({ timeWorld, onPlaceSelect }) {
  const [categoryFilter, setCategoryFilter] = useState("all");
  const categories = timeWorld?.categories ?? [];
  useEffect(() => {
    if (categoryFilter !== "all" && !categories.some((category) => category.key === categoryFilter)) {
      setCategoryFilter("all");
    }
  }, [categories, categoryFilter]);
  const populatedScopes = (timeWorld?.scopes ?? [])
    .map((scope) => ({
      ...scope,
      assertions: categoryFilter === "all"
        ? scope.assertions
        : scope.assertions.filter((assertion) => assertion.content_category?.key === categoryFilter),
    }))
    .filter((scope) => scope.assertions.length > 0);
  const scopeKeys = { local: "scopeLocalArea", regional: "scopeRegionalArea", macroregional: "scopeMacroregional", global: "scopeWorldwide" };
  if (!timeWorld?.scopes?.some((scope) => scope.count > 0)) {
    return <p className="empty compact">{t("noGeoEvents")}</p>;
  }
  const selection = timeWorld.selection;
  const selectionRange = selection
    ? selection.time_unbounded
      ? t("allTimes")
      : selection.start_year === selection.end_year
      ? yearLabel(selection.focus_year)
      : `${yearLabel(selection.start_year)}–${yearLabel(selection.end_year)}`
    : "";
  const patterns = timeWorld.patterns ?? [];
  return (
    <div className="world-scopes">
      {selection && <section className="world-context-card">
        <span>{t("timeSelection")}</span>
        <strong>{selectionRange}</strong>
        {!selection.time_unbounded && <p>{selection.window_years > 0
          ? t("centeredWindow", { focus: yearLabel(selection.focus_year), years: selection.window_years })
          : t("exactYearSelection", { year: yearLabel(selection.focus_year) })}</p>}
        <dl>
          <div><dt>{t("referencePlace")}</dt><dd>{selection.reference_place.space_unbounded
            ? t("worldwide")
            : `${selection.reference_place.name} · ${selection.reference_place.radius_km} km`}</dd></div>
          <div><dt>{t("meaningOfResults")}</dt><dd>{t("datedStatementsExplain")}</dd></div>
        </dl>
        <p className="selection-note">{t("independentAxesNote")}</p>
        {timeWorld.truncated && <p className="selection-note">{t("rankedResultsLimited", {
          shown: timeWorld.count,
          total: timeWorld.total_count,
        })}</p>}
      </section>}

      {categories.length > 0 && <section className="category-overview" aria-label={t("categories")}>
        <div className="section-heading"><h3>{t("categories")}</h3><span>{timeWorld.count} {t(timeWorld.count === 1 ? "finding" : "findings")}</span></div>
        <div className="category-filters">
          <button className={categoryFilter === "all" ? "active" : ""} type="button" onClick={() => setCategoryFilter("all")}>{t("categoryAll")} <b>{timeWorld.count}</b></button>
          {categories.map((category) => (
            <button className={categoryFilter === category.key ? "active" : ""} type="button" key={category.key} onClick={() => setCategoryFilter(category.key)}>
              {categoryLabel(category.key)} <b>{category.count}</b>
            </button>
          ))}
        </div>
      </section>}

      {patterns.length > 0 && <section className="pattern-overview" aria-label={t("patternsHypotheses")}>
        <div className="section-heading"><h3>{t("patternsHypotheses")}</h3><span>{t("interpretCautiously")}</span></div>
        {patterns.map((pattern) => (
          <button className={`pattern-card ${pattern.evidence_level}`} type="button" key={pattern.key} onClick={() => setCategoryFilter(pattern.category)}>
            <span>{pattern.evidence_level === "coincidence" ? t("openQuestion") : t("automaticPattern")}</span>
            <strong>{t(`patternTitle_${pattern.key}`, { category: categoryLabel(pattern.category) })}</strong>
            <p>{t(`patternText_${pattern.key}`, { count: pattern.support_count, category: categoryLabel(pattern.category) })}</p>
            <small>{t(`patternLimit_${pattern.limitation}`)}</small>
          </button>
        ))}
      </section>}

      {populatedScopes.map((scope) => (
        <section className="world-scope" key={scope.key}>
          <div className="section-heading sticky-heading">
            <h3>{scopeKeys[scope.key] ? t(scopeKeys[scope.key]) : scope.label}</h3>
            <span>{scope.assertions.length} {t(scope.assertions.length === 1 ? "finding" : "findings")}</span>
          </div>
          {scope.assertions.map((assertion) => (
            <AssertionCard key={assertion.id} assertion={assertion} onPlaceSelect={onPlaceSelect} />
          ))}
        </section>
      ))}
      <p className="scope-note">{t("scopeBasis")}</p>
    </div>
  );
}

function localizedMetadata(values) {
  if (!values || typeof values !== "object") return "";
  return values[uiLocale] || values.en || values.de || values.fr || Object.values(values)[0] || "";
}

function processPeriod(process) {
  const start = process.temporal_extent?.start_year;
  const end = process.temporal_extent?.end_year;
  if (start == null && end == null) return t("notSpecified");
  if (start == null) return `${t("until")} ${yearLabel(end)}`;
  if (end == null || end === start) return yearLabel(start);
  return `${yearLabel(start)}–${yearLabel(end)}`;
}

function HistoricalProcesses({ data }) {
  if (!data?.count) return null;
  return (
    <section className="historical-processes" aria-label={t("evidenceDossiers")}>
      <div className="section-heading dossier-heading">
        <h3>{t("evidenceDossiers")}</h3>
        <span>{data.count} {t(data.count === 1 ? "dossier" : "dossiers")}</span>
      </div>
      <p className="dossier-intro">{t("dossierIntro")}</p>
      {data.processes.map((process) => {
        const summary = localizedMetadata(process.metadata?.summaries) || process.summary;
        const question = localizedMetadata(process.metadata?.editorial_questions);
        const relations = process.assertion_relations ?? [];
        const evidenceLevels = process.evidence_levels ?? {};
        const integrityIssues = process.integrity_issues ?? [];
        return (
          <article className={`dossier-card ${process.status}`} key={process.id}>
            <div className="dossier-meta">
              <span>{translatedCode(process.process_type, PROCESS_TYPE_KEYS, process.process_type_label)}</span>
              <strong>{processPeriod(process)}</strong>
            </div>
            <h4>{process.entity.canonical_name}</h4>
            <p>{summary}</p>
            {question && <div className="dossier-question"><span>{t("editorialQuestion")}</span><strong>{question}</strong></div>}
            <div className="dossier-evidence" aria-label={t("evidenceProfile")}>
              {Object.entries(evidenceLevels).filter(([, count]) => count > 0).map(([level, count]) => (
                <span className={level} key={level}>{t(ASSERTION_RELATION_EVIDENCE_KEYS[level])} · {count}</span>
              ))}
            </div>
            {relations.length > 0 && <div className="dossier-findings">
              {relations.slice(0, 4).map((relation) => {
                const start = relation.assertion?.temporal_extent?.start?.year;
                const end = relation.assertion?.temporal_extent?.end?.year;
                return (
                  <div className={`dossier-finding ${relation.evidence_level}`} key={relation.id}>
                    <span>{start == null ? t("notSpecified") : end && end !== start ? `${yearLabel(start)}–${yearLabel(end)}` : yearLabel(start)}</span>
                    <strong>{relation.assertion?.subject?.canonical_name}</strong>
                    <small>{t(ASSERTION_RELATION_EVIDENCE_KEYS[relation.evidence_level])}</small>
                  </div>
                );
              })}
            </div>}
            <footer>
              <span>{Math.round(Number(process.confidence) * 100)} % {t("confidence")}</span>
              {integrityIssues.length > 0 && <span className="review-open">{t("processReviewOpen")}</span>}
            </footer>
          </article>
        );
      })}
    </section>
  );
}

function sourceLink(dataset) {
  return dataset?.source?.url || dataset?.asset_uri || "";
}

const EVENT_TYPE_KEYS = {
  volcano: "eventVolcano", earthquake: "eventEarthquake", tsunami: "eventTsunami", storm_surge: "eventStormSurge", drought: "eventDrought", heatwave: "eventHeatwave",
  frost: "eventFrost", flood: "eventFlood", river_course_change: "eventRiverCourseChange", other: "eventOther",
};
const OBSERVATION_METHOD_KEYS = { measurement: "methodMeasurement", reconstruction: "methodReconstruction", documentary: "methodDocumentary" };
const OBSERVATION_SCOPE_KEYS = { local: "scopeLocal", regional: "scopeRegional", hemispheric: "scopeHemispheric", global: "scopeGlobal" };
const RELATION_TYPE_KEYS = { documented: "relationDocumented", possible: "relationPossible", coincidence: "relationCoincidence", disputed: "relationDisputed" };

function translatedCode(value, keys, fallback) {
  return keys[value] ? t(keys[value]) : fallback;
}

function ClimateGraph({ series }) {
  const points = series.points ?? [];
  if (points.length < 2) return null;
  const width = 360;
  const height = 176;
  const padding = { top: 14, right: 12, bottom: 28, left: 39 };
  const values = points.map((point) => Number(point.value));
  if (series.baseline != null) values.push(Number(series.baseline));
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const spread = maximum - minimum || 1;
  minimum -= spread * 0.12;
  maximum += spread * 0.12;
  const firstYear = points[0].year;
  const lastYear = points.at(-1).year;
  const x = (year) => padding.left + ((year - firstYear) / Math.max(1, lastYear - firstYear)) * (width - padding.left - padding.right);
  const y = (value) => padding.top + ((maximum - value) / (maximum - minimum)) * (height - padding.top - padding.bottom);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(point.year).toFixed(1)},${y(Number(point.value)).toFixed(1)}`).join(" ");
  const focusPoint = series.focus_point;
  const baselineY = series.baseline == null ? null : y(Number(series.baseline));
  const gridValues = [maximum, (maximum + minimum) / 2, minimum];
  const color = series.method === "measurement" ? "#75d9b1" : series.method === "reanalysis" ? "#72bce8" : "#e1b86a";
  const digits = series.unit === "mm" ? 0 : 1;
  const focusX = focusPoint ? x(focusPoint.year) : null;
  const showSeparateFocusYear = focusX != null && focusX - padding.left > 42 && width - padding.right - focusX > 42;

  return (
    <figure className={`climate-figure ${series.method}`}>
      <figcaption>
        <div><span>{series.method_label}</span><h3>{series.title}</h3></div>
        <strong>{series.focus_point ? `${formatNumber(series.focus_point.value)} ${series.unit}` : "–"}</strong>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("graphFromTo", { title: series.title, first: firstYear, last: lastYear })}>
        {gridValues.map((value) => (
          <g key={value}>
            <line className="climate-grid" x1={padding.left} x2={width - padding.right} y1={y(value)} y2={y(value)} />
            <text className="climate-axis-value" x={padding.left - 6} y={y(value) + 3}>{value.toFixed(digits)}</text>
          </g>
        ))}
        {baselineY != null && <line className="climate-baseline" x1={padding.left} x2={width - padding.right} y1={baselineY} y2={baselineY} />}
        {focusPoint && <line className="climate-focus-line" x1={focusX} x2={focusX} y1={padding.top} y2={height - padding.bottom} />}
        <path className="climate-line" style={{ stroke: color }} d={line} />
        {focusPoint && <circle className="climate-focus-point" style={{ fill: color }} cx={focusX} cy={y(Number(focusPoint.value))} r="4.5" />}
        <text className="climate-axis-year" x={padding.left} y={height - 8}>{firstYear}</text>
        {showSeparateFocusYear && <text className="climate-axis-year focus" x={focusX} y={height - 8}>{focusPoint.year}</text>}
        <text className="climate-axis-year end" x={width - padding.right} y={height - 8}>{lastYear}</text>
      </svg>
      <div className="climate-reading">
        <strong>{series.focus_interpretation}</strong>
        {series.change_summary && <span>{series.change_summary}</span>}
        <span>{series.location_label} · {t("distanceFromPlace", { distance: series.distance_km })}</span>
        <span>{series.reference_label}</span>
      </div>
      <details className="climate-details">
        <summary>{t("graphDetails")}</summary>
        <p>{series.spatial_resolution}. {series.uncertainty}</p>
        <a href={series.source.url} target="_blank" rel="noreferrer">{series.source.provider} · {series.source.license} ↗</a>
      </details>
    </figure>
  );
}

function ClimateTable({ table }) {
  const monthName = (month) => new Intl.DateTimeFormat(uiLocale, { month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(2020, month - 1, 1)));
  return (
    <figure className="climate-table-card">
      <figcaption>
        <div><span>{t("climateNormal")}</span><h3>{table.title}</h3></div>
        <strong>{table.period}</strong>
      </figcaption>
      <p>{table.note}</p>
      <div className="climate-table-scroll">
        <table>
          <thead><tr><th>{t("month")}</th><th>{t("temperature")}</th><th>{t("precipitation")}</th></tr></thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.month}>
                <th>{monthName(row.month)}</th>
                <td>{formatNumber(row.temperature, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} {table.temperature_unit}</td>
                <td>{formatNumber(row.precipitation, { maximumFractionDigits: 0 })} {table.precipitation_unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <a href={table.source.url} target="_blank" rel="noreferrer">{table.source.provider} · {table.source.license} ↗</a>
    </figure>
  );
}

function formatHistoricalDate(value) {
  if (!value || /^\d{1,4}$/.test(String(value))) return value;
  const parts = String(value).split(/[-/]/).map(Number);
  if (parts.length < 2 || parts.some(Number.isNaN)) return value;
  return new Intl.DateTimeFormat(uiLocale, {
    day: parts.length === 3 ? "numeric" : undefined,
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] || 1)));
}

function EnvironmentalEventFacts({ event }) {
  const metadata = event.metadata ?? {};
  const start = metadata.dates?.start;
  const end = metadata.dates?.end;
  const dateLabel = start
    ? `${formatHistoricalDate(start)}${end && end !== start ? ` – ${formatHistoricalDate(end)}` : ""}`
    : null;
  const facts = [
    dateLabel && [t("eventDate"), dateLabel],
    metadata.flood_source && [t("riverOrSource"), metadata.flood_source],
    metadata.observation_count != null && [t("documentedObservations"), formatNumber(metadata.observation_count, { maximumFractionDigits: 0 })],
    metadata.maximum_water_height_m != null && [t("maximumWaterHeight"), `${formatNumber(metadata.maximum_water_height_m, { maximumFractionDigits: 2 })} m`],
    metadata.magnitude != null && [t("magnitude"), formatNumber(metadata.magnitude, { maximumFractionDigits: 1 })],
    metadata.depth_km != null && [t("earthquakeDepth"), `${formatNumber(metadata.depth_km, { maximumFractionDigits: 1 })} km`],
    metadata.intensity != null && [t("earthquakeIntensity"), formatNumber(metadata.intensity, { maximumFractionDigits: 1 })],
    metadata.area_flooded_km2 != null && [t("floodedArea"), `${formatNumber(metadata.area_flooded_km2, { maximumFractionDigits: 0 })} km²`],
    metadata.persons_affected != null && [t("peopleAffected"), formatNumber(metadata.persons_affected, { maximumFractionDigits: 0 })],
    (metadata.fatalities ?? metadata.fatalities_at_observation_sites) != null && [t("fatalities"), formatNumber(metadata.fatalities ?? metadata.fatalities_at_observation_sites, { maximumFractionDigits: 0 })],
    metadata.losses_2020_euro != null && [t("documentedLoss"), new Intl.NumberFormat(uiLocale, { style: "currency", currency: "EUR", notation: "compact", maximumFractionDigits: 1 }).format(metadata.losses_2020_euro)],
  ].filter(Boolean);
  if (!facts.length && !metadata.cause) return null;
  return (
    <>
      {metadata.cause && <p className="event-cause"><strong>{t("reportedCause")}:</strong> {metadata.cause}</p>}
      {metadata.notes && <p className="event-cause"><strong>{t("sourceNote")}:</strong> {metadata.notes}</p>}
      {facts.length > 0 && <dl className="event-facts">
        {facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>}
      {metadata.spatial_note && <p className="environment-uncertainty">{t("affectedRegionNote")}</p>}
    </>
  );
}

function LivingConditions({ conditions }) {
  if (!conditions) {
    return <p className="empty compact">{t("livingLoading")}</p>;
  }
  const climateSeries = conditions.climate_series ?? [];
  const climateTables = climateSeries.flatMap((series) => series.monthly_table ? [series.monthly_table] : []);
  const hasClimate = climateSeries.length > 0;
  const hasEvents = (conditions.event_count ?? 0) > 0;
  const hasObservations = (conditions.observation_count ?? 0) > 0;
  const hasRelations = (conditions.relation_count ?? 0) > 0;
  if (!hasClimate && !hasEvents && !hasObservations && !hasRelations) {
    return <p className="empty compact">{t("noLivingData")}</p>;
  }
  return (
    <div className="living-conditions">
      {conditions.reference_place && <section className="living-reference-card">
        <span>{t("referencePlace")}</span>
        <h3>{conditions.reference_place.name}</h3>
        <p>{Number(conditions.reference_place.center.latitude).toFixed(2)}°, {Number(conditions.reference_place.center.longitude).toFixed(2)}° · {conditions.reference_place.radius_km} km</p>
        <dl>
          <div><dt>{t("historicalSelection")}</dt><dd>{yearLabel(conditions.time_range.start_year)}{conditions.time_range.end_year !== conditions.time_range.start_year ? `–${yearLabel(conditions.time_range.end_year)}` : ""}</dd></div>
          {hasClimate && <div><dt>{t("modernComparison")}</dt><dd>{t("modernComparisonAt")}</dd></div>}
        </dl>
      </section>}
      <section className="living-summary">
        <span aria-hidden="true">◌</span>
        <div>
          <h3>{t("environmentalSituation")}</h3>
          <p>{conditions.assessment}</p>
        </div>
      </section>

      {hasClimate && <section className="living-section climate-series-section">
        <div className="section-heading">
          <h3>{t("climateDevelopment")}</h3><span>{conditions.climate_series_count ?? 0} {t((conditions.climate_series_count ?? 0) === 1 ? "graph" : "graphs")}</span>
        </div>
        {climateTables.map((table) => <ClimateTable key={table.id} table={table} />)}
        {climateSeries.map((series) => (
          <ClimateGraph key={series.id} series={series} />
        ))}
        {conditions.climate_warnings?.length > 0 && <p className="environment-uncertainty">{t("climateWarning")}</p>}
      </section>}

      {hasEvents && <section className="living-section">
        <div className="section-heading">
          <h3>{t("naturalEvents")}</h3><span>{conditions.event_count}</span>
        </div>
        {conditions.events.map((event) => (
          <article className="environment-card" key={event.id}>
            <div className="environment-meta">
              <span>{translatedCode(event.event_type, EVENT_TYPE_KEYS, event.event_type_label)}</span>
              <span>{event.distance_km == null ? t("supraregional") : t("distanceAway", { distance: Math.round(event.distance_km) })}</span>
            </div>
            <h3>{event.name}</h3>
            {event.description && !event.metadata?.hanze_type && <p>{event.description}</p>}
            <EnvironmentalEventFacts event={event} />
            <div className="environment-values">
              <strong>{yearLabel(event.time_start_year)}{event.time_end_year !== event.time_start_year ? `–${yearLabel(event.time_end_year)}` : ""}</strong>
              <span>{t("confidence")} {Math.round(Number(event.confidence) * 100)} %</span>
              {event.temporal_uncertainty_years > 0 && <span>± {event.temporal_uncertainty_years} {t(event.temporal_uncertainty_years === 1 ? "year" : "years")}</span>}
            </div>
            {sourceLink(event.dataset) && <a href={sourceLink(event.dataset)} target="_blank" rel="noreferrer">{event.dataset.provider}: {t("openSource")}</a>}
          </article>
        ))}
      </section>}

      {hasObservations && <section className="living-section">
        <div className="section-heading">
          <h3>{t("climateAtmosphere")}</h3><span>{conditions.observation_count}</span>
        </div>
        {conditions.observations.map((observation) => (
          <article className="environment-card observation" key={observation.id}>
            <div className="environment-meta">
              <span>{translatedCode(observation.method, OBSERVATION_METHOD_KEYS, observation.method_label)}</span><span>{translatedCode(observation.spatial_scope, OBSERVATION_SCOPE_KEYS, observation.spatial_scope_label)}</span>
            </div>
            <h3>{observation.variable}</h3>
            <div className="observation-reading">
              {observation.value != null ? <strong>{formatNumber(observation.value, { maximumFractionDigits: 4 })} <small>{observation.unit}</small></strong> : <strong>{observation.value_text}</strong>}
              <span>{yearLabel(observation.time_start_year)}{observation.time_end_year !== observation.time_start_year ? `–${yearLabel(observation.time_end_year)}` : ""}</span>
            </div>
            {observation.aggregation && <p>{observation.aggregation}</p>}
            {(observation.reference_period_start_year != null || observation.metadata?.uncertainty_note) && (
              <p className="environment-uncertainty">
                {observation.reference_period_start_year != null && `${t("referencePeriod")} ${yearLabel(observation.reference_period_start_year)}–${yearLabel(observation.reference_period_end_year)}. `}
                {observation.metadata?.uncertainty_note}
              </p>
            )}
            {sourceLink(observation.dataset) && <a href={sourceLink(observation.dataset)} target="_blank" rel="noreferrer">{observation.dataset.provider}: {t("openDataset")}</a>}
          </article>
        ))}
      </section>}

      {hasRelations && <section className="living-section">
        <div className="section-heading">
          <h3>{t("historicalConsequences")}</h3><span>{conditions.relation_count}</span>
        </div>
        {conditions.relations.map((relation) => (
          <article className="environment-card relation" key={relation.id}>
            <div className="environment-meta"><span>{translatedCode(relation.relation_type, RELATION_TYPE_KEYS, relation.relation_type_label)}</span><span>{t("confidence")} {Math.round(Number(relation.confidence) * 100)} %</span></div>
            <h3>{relation.historical_assertion.subject.canonical_name}</h3>
            <p>{relation.summary}</p>
            {relation.mechanism && <p>{relation.mechanism}</p>}
            <p className="environment-uncertainty">{relation.uncertainty_note || conditions.uncertainty_note}</p>
          </article>
        ))}
      </section>}

      {conditions.datasets?.length > 0 && <details className="dataset-catalog">
        <summary>{t("availableEnvironmentalData")} ({conditions.datasets.length})</summary>
        {conditions.datasets.map((dataset) => (
          <a key={dataset.id} href={sourceLink(dataset)} target="_blank" rel="noreferrer">
            <strong>{dataset.title}</strong><span>{dataset.file_format} · {dataset.spatial_resolution_text}</span>
          </a>
        ))}
        <p>{conditions.storage_policy}</p>
      </details>}
      {(hasEvents || hasRelations) && <p className="causality-note">{conditions.uncertainty_note}</p>}
    </div>
  );
}

function EnvironmentalSearchResults({ search, onEventSelect }) {
  const [typeFilter, setTypeFilter] = useState("all");
  useEffect(() => setTypeFilter("all"), [search?.selection?.query]);
  if (!search) return <p className="empty compact">{t("natureSearchLoading")}</p>;
  const events = typeFilter === "all"
    ? search.events
    : search.events.filter((event) => event.event_type === typeFilter);
  const referencePlace = search.selection.reference_place;
  return (
    <div className="environment-search-results">
      <section className="global-search-note">
        <span>{referencePlace ? t("placeAllTimes", { place: referencePlace.name }) : t("globalAllTimes")}</span>
        <strong>{referencePlace
          ? search.selection.place_filter_method === "source_country"
            ? t("countryFilterApplied", { place: referencePlace.name })
            : t("placeFilterApplied", { radius: referencePlace.radius_km, place: referencePlace.name })
          : t("noPlaceTimeFilter")}</strong>
        {search.time_extent.start_year != null && (
          <p>{t("storedPeriod", {
            start: yearLabel(search.time_extent.start_year),
            end: yearLabel(search.time_extent.end_year),
          })}</p>
        )}
      </section>
      {search.categories.length > 1 && <div className="category-filters nature-filters">
        <button className={typeFilter === "all" ? "active" : ""} type="button" onClick={() => setTypeFilter("all")}>{t("categoryAll")} <b>{search.count}</b></button>
        {search.categories.map((category) => (
          <button className={typeFilter === category.key ? "active" : ""} key={category.key} type="button" onClick={() => setTypeFilter(category.key)}>
            {translatedCode(category.key, EVENT_TYPE_KEYS, category.label)} <b>{category.count}</b>
          </button>
        ))}
      </div>}
      {events.map((event) => (
        <article className="environment-card global-event" key={event.id}>
          <div className="environment-meta">
            <span>{translatedCode(event.event_type, EVENT_TYPE_KEYS, event.event_type_label)}</span>
            <span>{event.map_point ? t("mapped") : t("locationUncertain")}</span>
          </div>
          <h3>{event.name}</h3>
          {event.description && <p>{event.description}</p>}
          <EnvironmentalEventFacts event={event} />
          <div className="environment-values">
            <strong>
              {event.time_start_year == null
                ? t("notSpecified")
                : `${yearLabel(event.time_start_year)}${event.time_end_year != null && event.time_end_year !== event.time_start_year ? `–${yearLabel(event.time_end_year)}` : ""}`}
            </strong>
            <span>{t("confidence")} {Math.round(Number(event.confidence) * 100)} %</span>
            {event.temporal_uncertainty_years > 0 && <span>± {event.temporal_uncertainty_years} {t(event.temporal_uncertainty_years === 1 ? "year" : "years")}</span>}
          </div>
          <div className="global-event-actions">
            {(event.metadata?.source_urls?.[0] || sourceLink(event.dataset)) && (
              <a href={event.metadata?.source_urls?.[0] || sourceLink(event.dataset)} target="_blank" rel="noreferrer">
                {event.dataset.provider}: {t("openSource")}
              </a>
            )}
            {event.map_point && <button type="button" onClick={() => onEventSelect(event)}>{t("enterNaturalEvent")}</button>}
          </div>
        </article>
      ))}
      {!events.length && <p className="empty compact">{t("noGlobalNaturalEvents")}</p>}
      {search.truncated && <p className="scope-note">{t("truncatedNaturalEvents", { count: search.returned_count, total: search.count })}</p>}
    </div>
  );
}

function LegalNotice({ onClose }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    dialogRef.current?.focus();
    function closeOnEscape(event) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="legal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="legal-dialog glass" role="dialog" aria-modal="true" aria-labelledby="legal-title" tabIndex="-1" ref={dialogRef}>
        <header>
          <div>
            <small>TRIPANION EXPLORE</small>
            <h2 id="legal-title">{t("copyrightSources")}</h2>
          </div>
          <button className="legal-close" type="button" onClick={onClose} aria-label={t("closeCopyright")}>×</button>
        </header>

        <p className="legal-owner">© 2026 Jürgen Beckmerhagen</p>
        <p>{t("legalIntro")}</p>

        <div className="legal-sources">
          <article>
            <h3>{t("map")}</h3>
            <p>{t("osmContributors")}</p>
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">{t("licenseContributors")}</a>
          </article>
          <article>
            <h3>{t("mapSoftware")}</h3>
            <p>Leaflet · BSD-2-Clause</p>
            <a href="https://github.com/Leaflet/Leaflet/blob/main/LICENSE" target="_blank" rel="noreferrer">{t("leafletLicense")}</a>
          </article>
          <article>
            <h3>{t("encyclopedicData")}</h3>
            <p>{t("wikimediaCopy")}</p>
            <a href={`https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/${uiLocale}`} target="_blank" rel="noreferrer">{t("wikimediaTerms")}</a>
          </article>
          <article>
            <h3>{t("archivesScience")}</h3>
            <p>{t("archivesCopy")}</p>
          </article>
          <article>
            <h3>{t("climateEnvironment")}</h3>
            <p>{t("climateSourcesCopy")}</p>
            <a href="https://volcano.si.edu/gvp_termsofuse.cfm" target="_blank" rel="noreferrer">{t("smithsonianTerms")}</a>
          </article>
        </div>

        <p className="legal-note">{t("legalNote")}</p>
        <a className="legal-tripanion" href="https://tripanion.com/" target="_blank" rel="noreferrer">{t("tripanionWebsite")}</a>
      </section>
    </div>
  );
}

function EventDossier({ dossier, view, onViewChange, timeWorld, onMomentSelect, onPlaceSelect }) {
  if (!dossier) {
    return <p className="empty compact">{t("dossierLoading")}</p>;
  }
  const range = dossier.end_year != null && dossier.end_year !== dossier.start_year
    ? `${yearLabel(dossier.start_year)}–${yearLabel(dossier.end_year)}`
    : yearLabel(dossier.start_year);
  return (
    <div className="event-dossier">
      <nav className="event-views" aria-label={t("dossierAria")}>
        {[
          ["overview", t("overview")],
          ["timeline", t("timeline")],
          ["places", t("places")],
          ["local", t("here")],
          ["world", t("world")],
        ].map(([key, label]) => (
          <button className={view === key ? "active" : ""} type="button" key={key} onClick={() => onViewChange(key)}>
            {label}
          </button>
        ))}
      </nav>

      {view === "overview" && (
        <section className="event-overview">
          <div className="event-period"><small>{t("period")}</small><strong>{range}</strong></div>
          <p>{dossier.description || t("noEventSummary")}</p>
          <dl>
            <div><dt>{t("startingPlace")}</dt><dd>{dossier.reference_place.name}</dd></div>
            <div><dt>{t("places")}</dt><dd>{dossier.place_count}</dd></div>
            <div><dt>{t("connectionHere")}</dt><dd>{dossier.local_count} {t(dossier.local_count === 1 ? "statement" : "statements")}</dd></div>
            <div><dt>{t("timePoints")}</dt><dd>{dossier.moment_count}</dd></div>
          </dl>
          <p className="uncertainty">{t("periodConfidence")}: {Math.round(dossier.temporal_confidence * 100)} % · {dossier.uncertainty_note}</p>
          <div className="event-sources">
            {dossier.sources.map((source) => <a key={`${source.provider}:${source.external_id}`} href={source.url} target="_blank" rel="noreferrer">{source.provider} ↗</a>)}
          </div>
        </section>
      )}
      {view === "timeline" && <PlaceTimeline timeline={dossier} onMomentSelect={onMomentSelect} />}
      {view === "places" && (
        dossier.places.length
          ? dossier.places.map((assertion) => <AssertionCard key={assertion.id} assertion={assertion} onPlaceSelect={onPlaceSelect} />)
          : <p className="empty compact">{t("researchingPlaces")}</p>
      )}
      {view === "local" && (
        dossier.local_assertions.length
          ? dossier.local_assertions.map((assertion) => <AssertionCard key={assertion.id} assertion={assertion} />)
          : <p className="empty compact">{t("noDirectEventLink", { place: dossier.reference_place.name })}</p>
      )}
      {view === "world" && <TimeWorld timeWorld={timeWorld} onPlaceSelect={onPlaceSelect} />}
    </div>
  );
}

function SpaceTimeFocusLayer({ exploration, bounds, onChange, obscured }) {
  const currentYear = new Date().getFullYear();
  const selectedStart = exploration.time_focus_year - exploration.time_window_years;
  const selectedEnd = exploration.time_focus_year + exploration.time_window_years;
  const minimumYear = Math.min(Number(bounds?.time?.min_year ?? -1000), selectedStart);
  const maximumYear = Math.max(Number(bounds?.time?.max_year ?? currentYear), currentYear, selectedEnd);
  const minimumDistance = Number(bounds?.distance?.min_km ?? 1);
  const maximumDistance = Number(bounds?.distance?.max_km ?? 1000);
  const startYear = exploration.time_unbounded ? minimumYear : clamp(selectedStart, minimumYear, maximumYear);
  const endYear = exploration.time_unbounded ? maximumYear : clamp(selectedEnd, minimumYear, maximumYear);
  const startPosition = Math.round(toLogAxisPosition(startYear, minimumYear, maximumYear) * FOCUS_AXIS_STEPS);
  const endPosition = Math.round(toLogAxisPosition(endYear, minimumYear, maximumYear) * FOCUS_AXIS_STEPS);
  const distancePosition = Math.round(toLogAxisPosition(
    exploration.space_unbounded ? maximumDistance : exploration.radius_km,
    minimumDistance,
    maximumDistance,
  ) * FOCUS_AXIS_STEPS);

  const applyTimeRange = (nextStartPosition, nextEndPosition) => {
    const rawStart = Math.round(fromLogAxisPosition(nextStartPosition / FOCUS_AXIS_STEPS, minimumYear, maximumYear));
    const rawEnd = Math.round(fromLogAxisPosition(nextEndPosition / FOCUS_AXIS_STEPS, minimumYear, maximumYear));
    const rangeStart = Math.min(rawStart, rawEnd);
    const rangeEnd = Math.max(rawStart, rawEnd);
    const focus = Math.round((rangeStart + rangeEnd) / 2);
    const windowYears = Math.max(0, Math.ceil((rangeEnd - rangeStart) / 2));
    onChange({
      time_focus_year: focus,
      time_window_years: windowYears,
      time_unbounded: false,
      anchor_mode: "time",
    }, 420);
  };

  const applyDistance = (position) => {
    const radius = Math.round(fromLogAxisPosition(position / FOCUS_AXIS_STEPS, minimumDistance, maximumDistance));
    onChange({ space_unbounded: false, radius_km: clamp(radius, minimumDistance, maximumDistance) }, 420);
  };

  const rangeLabel = exploration.time_unbounded
    ? `∞ · ${t("allTimes")}`
    : startYear === endYear
      ? yearLabel(startYear)
      : `${yearLabel(startYear)} – ${yearLabel(endYear)}`;

  return (
    <section className={`space-time-focus-layer ${obscured ? "obscured" : ""}`} aria-label={t("focusLayerAria")}>
      <div
        className="focus-time-axis"
        style={{ "--focus-start": `${startPosition / 100}%`, "--focus-end": `${endPosition / 100}%` }}
      >
        <div className="focus-axis-heading"><span>{t("timeRangeAxis")}</span><strong>{rangeLabel}</strong></div>
        <div className="focus-time-track" aria-hidden="true" />
        <input
          className="focus-time-slider focus-time-slider-start"
          aria-label={t("timeRangeStart")}
          type="range"
          min="0"
          max={FOCUS_AXIS_STEPS}
          value={startPosition}
          onInput={(event) => applyTimeRange(Math.min(Number(event.currentTarget.value), endPosition), endPosition)}
          onChange={(event) => applyTimeRange(Math.min(Number(event.currentTarget.value), endPosition), endPosition)}
        />
        <input
          className="focus-time-slider focus-time-slider-end"
          aria-label={t("timeRangeEnd")}
          type="range"
          min="0"
          max={FOCUS_AXIS_STEPS}
          value={endPosition}
          onInput={(event) => applyTimeRange(startPosition, Math.max(Number(event.currentTarget.value), startPosition))}
          onChange={(event) => applyTimeRange(startPosition, Math.max(Number(event.currentTarget.value), startPosition))}
        />
        <span className="focus-origin-label">0 · {yearLabel(minimumYear)}</span>
        <button
          className={exploration.time_unbounded ? "focus-infinity active" : "focus-infinity"}
          type="button"
          onClick={() => onChange({ time_unbounded: true, anchor_mode: "time" }, 0)}
          title={t("allTimes")}
        >∞</button>
      </div>

      <div
        className="focus-distance-axis"
        style={{ "--focus-distance": `${distancePosition / 100}%` }}
      >
        <div className="focus-distance-heading">
          <span>{t("distanceAxis")}</span>
          <strong>{exploration.space_unbounded ? `∞ · ${t("worldwide")}` : `${exploration.radius_km} km`}</strong>
        </div>
        <input
          className="focus-distance-slider"
          aria-label={t("distanceAxis")}
          type="range"
          min="0"
          max={FOCUS_AXIS_STEPS}
          value={distancePosition}
          onInput={(event) => applyDistance(Number(event.currentTarget.value))}
          onChange={(event) => applyDistance(Number(event.currentTarget.value))}
        />
        <button
          className={exploration.space_unbounded ? "focus-distance-infinity active" : "focus-distance-infinity"}
          type="button"
          onClick={() => onChange({ space_unbounded: true }, 0)}
          title={t("worldwide")}
        >∞</button>
        <span className="focus-distance-origin">0 · {minimumDistance} km</span>
      </div>
    </section>
  );
}

export default function App() {
  const currentYear = new Date().getFullYear();
  const [exploration, setExploration] = useState(null);
  const [queryInput, setQueryInput] = useState("");
  const [results, setResults] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [timeWorld, setTimeWorld] = useState(null);
  const [historicalProcesses, setHistoricalProcesses] = useState(null);
  const [livingConditions, setLivingConditions] = useState(null);
  const [environmentalSearch, setEnvironmentalSearch] = useState(null);
  const [livingOpen, setLivingOpen] = useState(false);
  const [eventDossier, setEventDossier] = useState(null);
  const [eventView, setEventView] = useState("overview");
  const [research, setResearch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resultsOpen, setResultsOpen] = useState(false);
  const [legalOpen, setLegalOpen] = useState(false);
  const [resolutionMessage, setResolutionMessage] = useState("");
  const [error, setError] = useState("");
  const [knowledgeBounds, setKnowledgeBounds] = useState({
    time: { min_year: -1000, max_year: currentYear },
    distance: { min_km: 1, max_km: 1000 },
  });
  const explorationRef = useRef(null);
  const cardsRef = useRef(null);
  const pendingPatchRef = useRef({});
  const patchTimerRef = useRef(null);
  const patchInFlightRef = useRef(false);

  const adoptExploration = useCallback((next) => {
    explorationRef.current = next;
    setExploration(next);
  }, []);

  const refreshResults = useCallback(async (contextId) => {
    if (!contextId) return;
    setLoading(true);
    setError("");
    try {
      const current = explorationRef.current;
      const [nextResults, nextTimeline, nextTimeWorld, nextEventDossier, nextLivingConditions, nextEnvironmentalSearch, nextHistoricalProcesses] = await Promise.all([
        loadExplorationResults(contextId),
        loadExplorationTimeline(contextId),
        loadTimeWorld(contextId),
        current?.focus_entity ? loadEventDossier(contextId) : Promise.resolve(null),
        loadLivingConditions(contextId),
        current?.query_mode === "environment" ? loadEnvironmentalEvents(contextId) : Promise.resolve(null),
        loadHistoricalProcesses(contextId),
      ]);
      setResults(nextResults);
      setTimeline(nextTimeline);
      setTimeWorld(nextTimeWorld);
      setEventDossier(nextEventDossier);
      setLivingConditions(nextLivingConditions);
      setEnvironmentalSearch(nextEnvironmentalSearch);
      setHistoricalProcesses(nextHistoricalProcesses);
    } catch {
      setError(t("apiUnavailable"));
    } finally {
      setLoading(false);
    }
  }, []);

  const flushPatch = useCallback(async () => {
    const current = explorationRef.current;
    if (!current || patchInFlightRef.current || Object.keys(pendingPatchRef.current).length === 0) return;
    window.clearTimeout(patchTimerRef.current);
    const patch = pendingPatchRef.current;
    pendingPatchRef.current = {};
    patchInFlightRef.current = true;
    setSaving(true);

    try {
      let updated;
      try {
        updated = await updateExplorationContext(current.id, patch, current.version);
      } catch (requestError) {
        if (!(requestError instanceof ApiError) || requestError.status !== 409) throw requestError;
        const latest = requestError.payload.exploration_context;
        updated = await updateExplorationContext(current.id, patch, latest.version);
      }
      const pending = pendingPatchRef.current;
      adoptExploration(mergeExploration(updated, pending));
      await refreshResults(updated.id);
    } catch {
      pendingPatchRef.current = { ...patch, ...pendingPatchRef.current };
      setError(t("contextSaveFailed"));
    } finally {
      patchInFlightRef.current = false;
      setSaving(false);
      if (Object.keys(pendingPatchRef.current).length > 0) {
        window.clearTimeout(patchTimerRef.current);
        patchTimerRef.current = window.setTimeout(flushPatch, 120);
      }
    }
  }, [adoptExploration, refreshResults]);

  const changeContext = useCallback((patch, delay = 280) => {
    const current = explorationRef.current;
    if (!current) return;
    pendingPatchRef.current = { ...pendingPatchRef.current, ...patch };
    adoptExploration(mergeExploration(current, patch));
    window.clearTimeout(patchTimerRef.current);
    patchTimerRef.current = window.setTimeout(flushPatch, delay);
  }, [adoptExploration, flushPatch]);

  useEffect(() => {
    let cancelled = false;
    loadKnowledgeBounds()
      .then((nextBounds) => {
        if (!cancelled) setKnowledgeBounds(nextBounds);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!resultsOpen) return undefined;
    const frame = window.requestAnimationFrame(() => {
      cardsRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    resultsOpen,
    exploration?.anchor_mode,
    exploration?.place_name,
    exploration?.time_focus_year,
    exploration?.time_window_years,
  ]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      let loaded;
      const existingId = contextIdFromUrl();
      const requestedLanguages = preferredLanguages();
      const initialContext = { ...DEFAULT_CONTEXT, languages: requestedLanguages };
      try {
        loaded = existingId ? await loadExplorationContext(existingId) : await createExplorationContext(initialContext);
      } catch (requestError) {
        if (existingId && requestError instanceof ApiError && requestError.status === 404) {
          loaded = await createExplorationContext(initialContext);
        } else {
          if (!cancelled) {
            setError(t("apiUnavailable"));
            setLoading(false);
          }
          return;
        }
      }
      if (cancelled) return;
      if (JSON.stringify(loaded.languages) !== JSON.stringify(requestedLanguages)) {
        try {
          loaded = await updateExplorationContext(
            loaded.id,
            { languages: requestedLanguages },
            loaded.version,
          );
        } catch (requestError) {
          if (requestError instanceof ApiError && requestError.status === 409) {
            loaded = requestError.payload.exploration_context;
          } else {
            throw requestError;
          }
        }
      }
      rememberContext(loaded.id);
      adoptExploration(loaded);
      setQueryInput(loaded.query);
      await refreshResults(loaded.id);
    }
    bootstrap();
    return () => {
      cancelled = true;
      window.clearTimeout(patchTimerRef.current);
    };
  }, [adoptExploration, refreshResults]);

  async function explore(event) {
    event.preventDefault();
    const query = queryInput.trim();
    if (!explorationRef.current || !query) return;
    setLoading(true);
    setError("");
    setResolutionMessage("");
    setResearch(null);
    await flushPatch();
    try {
      let resolved;
      try {
        resolved = await resolveExplorationInput(explorationRef.current.id, query, explorationRef.current.version);
      } catch (requestError) {
        if (!(requestError instanceof ApiError) || requestError.status !== 409) throw requestError;
        const latest = requestError.payload.exploration_context;
        adoptExploration(latest);
        resolved = await resolveExplorationInput(latest.id, query, latest.version);
      }
      adoptExploration(resolved.exploration_context);
      setEventView("overview");
      setResolutionMessage(
        resolved.resolved_as === "place"
          ? t("placeRecognized", { place: resolved.exploration_context.place_name })
          : resolved.resolved_as === "event"
            ? t("eventRecognized", { event: resolved.event.title, place: resolved.exploration_context.place_name })
            : resolved.resolved_as === "environment"
              ? resolved.environment?.place
                ? t("environmentAtPlaceRecognized", { query, place: resolved.environment.place.title })
                : t("environmentRecognized", { query })
              : t("topicAtPlace", { query }),
      );
      await refreshResults(resolved.exploration_context.id);
      if (resolved.resolved_as !== "environment") {
        const job = await startExplorationResearch(explorationRef.current.id);
        setResearch(job);
      }
      setResultsOpen(true);
    } catch (requestError) {
      setError(requestError instanceof ApiError && requestError.message
        ? requestError.message
        : t("inputFailed"));
    } finally {
      setLoading(false);
    }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setError(t("noGeolocation"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setResearch(null);
        setResolutionMessage("");
        setError("");
        changeContext({
          place_name: t("currentLocation"),
          latitude: coords.latitude,
          longitude: coords.longitude,
          map_zoom: 12,
          query: "",
          query_mode: "auto",
          anchor_mode: "space",
        }, 0);
      },
      () => setError(t("geolocationDenied")),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }

  async function startTimeWorldResearch(patch) {
    changeContext({ ...patch, anchor_mode: "time" }, 0);
    setResultsOpen(true);
    await flushPatch();
    if (explorationRef.current.time_unbounded || explorationRef.current.space_unbounded) {
      setResearch(null);
      return;
    }
    try {
      const job = await startExplorationResearch(explorationRef.current.id);
      setResearch(job);
    } catch {
      setError(t("worldResearchFailed"));
    }
  }

  function pivotToTime(moment) {
    const endYear = moment.end_year ?? moment.year;
    const focusYear = Math.floor((moment.year + endYear) / 2);
    const windowYears = Math.max(focusYear - moment.year, endYear - focusYear);
    startTimeWorldResearch({
      time_focus_year: focusYear,
      time_window_years: windowYears,
      time_unbounded: false,
    });
  }

  function pivotToPlace(assertion) {
    if (!assertion.location) return;
    const placeName = assertion.subject.canonical_name;
    setQueryInput(placeName);
    setResearch(null);
    setResolutionMessage("");
    setError("");
    changeContext({
      place_name: placeName,
      latitude: assertion.location.latitude,
      longitude: assertion.location.longitude,
      map_zoom: 12,
      query: placeName,
      query_mode: "place",
      anchor_mode: "space",
    }, 0);
    setResultsOpen(true);
  }

  async function pivotToEnvironmentalEvent(event) {
    if (!event.map_point) return;
    const hasTime = event.time_start_year != null;
    const endYear = event.time_end_year ?? event.time_start_year;
    const focusYear = hasTime ? Math.floor((event.time_start_year + endYear) / 2) : null;
    const windowYears = hasTime ? Math.max(focusYear - event.time_start_year, endYear - focusYear) : null;
    setQueryInput("");
    setResearch(null);
    setResolutionMessage(t("naturalEventEntered", { event: event.name }));
    setError("");
    setLivingOpen(false);
    changeContext({
      place_name: event.name,
      latitude: event.map_point.latitude,
      longitude: event.map_point.longitude,
      map_zoom: 6,
      ...(hasTime ? { time_focus_year: focusYear, time_window_years: windowYears, time_unbounded: false } : {}),
      query: "",
      query_mode: "auto",
      anchor_mode: hasTime ? "time" : "space",
      environmental_event_types: [],
      environmental_place_name: "",
    }, 0);
    setResultsOpen(true);
    if (hasTime) {
      await flushPatch();
      try {
        const job = await startExplorationResearch(explorationRef.current.id);
        setResearch(job);
      } catch {
        setError(t("worldResearchFailed"));
      }
    }
  }

  useEffect(() => {
    if (!research || ["complete", "partial", "failed"].includes(research.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const update = await loadResearch(research.id);
        setResearch(update);
        if (["complete", "partial"].includes(update.status)) refreshResults(explorationRef.current?.id);
      } catch {
        window.clearInterval(timer);
      }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [research, refreshResults]);

  if (!exploration) {
    return <main className="boot"><div className="loader" /><p>{error || t("preparing")}</p></main>;
  }

  const worldEvents = (timeWorld?.scopes?.flatMap((scope) => scope.assertions) ?? []).filter(canEnterAssertionLocation);
  const eventPlaces = eventDossier?.places?.filter((item) => item.location) ?? [];
  const isSpaceAnchor = exploration.anchor_mode === "space";
  const isEventAnchor = exploration.anchor_mode === "event";
  const isTimeAnchor = exploration.anchor_mode === "time";
  const isEnvironmentAnchor = exploration.anchor_mode === "environment";
  const hasEnvironmentalSearch = (exploration.environmental_event_types?.length ?? 0) > 0;
  const environmentalEvents = environmentalSearch?.events ?? [];
  const livingCount = (livingConditions?.event_count ?? 0) + (livingConditions?.observation_count ?? 0) + (livingConditions?.relation_count ?? 0) + (livingConditions?.climate_series_count ?? 0);

  return (
    <main className="app-shell">
      <MapContainer
        center={[exploration.center.latitude, exploration.center.longitude]}
        zoom={Number(exploration.map_zoom)}
        zoomControl
        zoomSnap={0.25}
        zoomDelta={0.25}
        wheelPxPerZoomLevel={120}
        maxBounds={[[-85, -180], [85, 180]]}
        maxBoundsViscosity={1}
        closePopupOnClick={false}
        className="map"
      >
        <TileLayer noWrap attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {!exploration.space_unbounded && (!isEnvironmentAnchor || exploration.environmental_place_name) && <Circle center={[exploration.center.latitude, exploration.center.longitude]} radius={exploration.radius_km * 1000} pathOptions={{ color: "#75d9b1", fillColor: "#75d9b1", fillOpacity: 0.12 }} />}
        {isTimeAnchor && worldEvents.map((assertion) => assertion.location && (
          <AssertionMapMarker
            key={assertion.id}
            assertion={assertion}
          />
        ))}
        {isEventAnchor && eventPlaces.slice(0, 160).map((assertion) => (
          <Marker
            key={assertion.id}
            position={[assertion.location.latitude, assertion.location.longitude]}
            icon={categoryMarkerIcon(assertion.content_category?.key ?? "event")}
            eventHandlers={{ click: () => pivotToPlace(assertion) }}
          />
        ))}
        {isEnvironmentAnchor && environmentalEvents.filter((event) => event.map_point).slice(0, 300).map((event) => (
          <Marker
            key={event.id}
            position={[event.map_point.latitude, event.map_point.longitude]}
            icon={categoryMarkerIcon("natural_event", ENVIRONMENTAL_MARKER_SYMBOLS[event.event_type] ?? ENVIRONMENTAL_MARKER_SYMBOLS.other)}
            eventHandlers={{ click: () => pivotToEnvironmentalEvent(event) }}
          />
        ))}
        <MapController
          exploration={exploration}
          eventPlaces={eventPlaces}
          environmentalEvents={environmentalEvents}
          onPlaceChange={async (patch) => {
            setQueryInput("");
            setResearch(null);
            setResolutionMessage("");
            setError("");
            const latitude = Number(patch.latitude);
            const longitude = Number(patch.longitude);
            const coordinateName = t("mapPoint", {
              latitude: formatNumber(latitude, { minimumFractionDigits: 3, maximumFractionDigits: 3 }),
              longitude: formatNumber(longitude, { minimumFractionDigits: 3, maximumFractionDigits: 3 }),
            });
            changeContext({ ...patch, place_name: coordinateName, query: "", query_mode: "auto", anchor_mode: "space" }, 0);
            try {
              const resolvedPlace = await reverseGeocodePlace(latitude, longitude, uiLocale);
              const currentCenter = explorationRef.current?.center;
              const stillSelected = currentCenter
                && Math.abs(Number(currentCenter.latitude) - latitude) < 0.00001
                && Math.abs(Number(currentCenter.longitude) - longitude) < 0.00001;
              if (resolvedPlace?.name && stillSelected) {
                changeContext({
                  place_name: resolvedPlace.name,
                  query: resolvedPlace.name,
                  query_mode: "place",
                  anchor_mode: "space",
                }, 0);
              }
            } catch {
              // Der koordinatengenaue Bezug bleibt auch ohne externe Ortsauflösung gültig.
            }
          }}
          onZoomChange={(map_zoom) => changeContext({ map_zoom })}
        />
      </MapContainer>

      <div className="shade" />
      <SpaceTimeFocusLayer
        exploration={exploration}
        bounds={knowledgeBounds}
        onChange={changeContext}
        obscured={resultsOpen || legalOpen}
      />
      <div className="brand-bar" aria-label="Tripanion Explore">
        <a className="brand-link" href="https://tripanion.com/" target="_blank" rel="noreferrer" aria-label={t("tripanionWebsiteAria")}>
          &gt;tripanion_Explore
        </a>
        <button className="legal-trigger" type="button" onClick={() => setLegalOpen(true)}>{t("sources")}</button>
      </div>
      <section className="top-overlay">
        <form className="search" onSubmit={explore}>
          <span className="search-icon" aria-hidden="true">⌕</span>
          <input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder={t("discoverTopic")} aria-label={t("discoverTopic")} />
          <button disabled={loading}>{loading ? "…" : t("explore")}</button>
        </form>
        <div className="invitation">
          <span>{exploration.place_name}</span>
          <h1>{t("invitation")}</h1>
          <p>{t("invitationCopy")}</p>
        </div>
      </section>

      <button className="results-toggle glass" onClick={() => setResultsOpen((open) => !open)} aria-expanded={resultsOpen} aria-controls="results-panel">
        <span>{livingOpen ? livingCount : isEnvironmentAnchor ? environmentalSearch?.count ?? 0 : isEventAnchor ? eventDossier?.place_count ?? 0 : results?.count ?? 0} {t("discoveries")}</span><span aria-hidden="true">{resultsOpen ? "×" : "↑"}</span>
      </button>

      <section className={`controls glass ${resultsOpen ? "behind-sheet" : ""}`} aria-label={t("spaceTimeFocus")}>
        <div className="time-control">
          <div className="control-title">
            <label htmlFor="year">{t("time")}</label>
            <input className="year-input" aria-label={t("enterYear")} type="number" min="-5000000000" max="20000" value={exploration.time_focus_year} onChange={(event) => changeContext({ time_focus_year: Number(event.target.value), time_unbounded: false, anchor_mode: "time" })} />
          </div>
          <input id="year" type="range" min="-1000" max={currentYear} value={Math.max(-1000, Math.min(currentYear, exploration.time_focus_year))} onChange={(event) => changeContext({ time_focus_year: Number(event.target.value), time_unbounded: false, anchor_mode: "time" })} />
        </div>
        <div className="focus-row">
          <label>{t("timeWindow")}
            <select value={exploration.time_unbounded ? "all" : String(exploration.time_window_years)} onChange={(event) => changeContext(event.target.value === "all"
              ? { time_unbounded: true, anchor_mode: "time" }
              : { time_unbounded: false, time_window_years: Number(event.target.value), anchor_mode: "time" }, 0)}>
              {![0, 5, 50].includes(Number(exploration.time_window_years)) && (
                <option value={exploration.time_window_years}>{t("eventWindow", { years: Number(exploration.time_window_years) * 2 })}</option>
              )}
              <option value="0">{t("exact")}</option><option value="5">{t("tenYears")}</option><option value="50">{t("hundredYears")}</option>
              <option value="all">∞ {t("allTimes")}</option>
            </select>
          </label>
          <label>{t("radius")}
            <select value={exploration.space_unbounded ? "all" : String(exploration.radius_km)} onChange={(event) => changeContext(event.target.value === "all"
              ? { space_unbounded: true }
              : { space_unbounded: false, radius_km: Number(event.target.value) }, 0)}>
              {[1, 10, 25, 50, 250, 1000].map((radius) => <option key={radius} value={radius}>{radius} km</option>)}
              <option value="all">🌍 {t("worldwide")}</option>
            </select>
          </label>
          <button className="location-button" type="button" onClick={useCurrentLocation} title={t("useCurrentLocation")}><span aria-hidden="true">◎</span><span>{t("myPlace")}</span></button>
        </div>
        <div className="context-state" aria-live="polite">
          {isEnvironmentAnchor
            ? <><span>{exploration.environmental_place_name || t("worldwide")}</span><span>{t("allTimes")}</span><span>{exploration.environmental_place_name ? `${exploration.radius_km} km` : t("noFilters")}</span></>
            : <><span>{exploration.space_unbounded ? t("worldwide") : exploration.place_name}</span><span>{exploration.time_unbounded ? t("allTimes") : yearLabel(exploration.time_focus_year)}</span><span>{exploration.space_unbounded ? t("noFilters") : `${exploration.radius_km} km`}</span></>}<small>{saving ? t("saving") : t("saved")}</small>
        </div>
      </section>

      <aside id="results-panel" className={`results glass ${resultsOpen ? "open" : ""}`} aria-label={t("discoveriesAria")}>
        <nav className={`pivot-switch ${exploration.focus_entity || hasEnvironmentalSearch ? "has-event" : ""}`} aria-label={t("explorationDirection")}>
          <button className={!livingOpen && isSpaceAnchor ? "active" : ""} type="button" onClick={() => { setLivingOpen(false); changeContext({ anchor_mode: "space" }, 0); }}>
            <span>{t("placeToTime")}</span><small>{t("historyHere")}</small>
          </button>
          {exploration.focus_entity && (
            <button className={!livingOpen && isEventAnchor ? "active" : ""} type="button" onClick={() => { setLivingOpen(false); changeContext({ anchor_mode: "event" }, 0); }}>
              <span>{t("eventTab")}</span><small>{exploration.focus_entity.canonical_name}</small>
            </button>
          )}
          {hasEnvironmentalSearch && (
            <button className={!livingOpen && isEnvironmentAnchor ? "active" : ""} type="button" onClick={() => { setLivingOpen(false); changeContext({ anchor_mode: "environment" }, 0); }}>
              <span>{t("naturalEvents")}</span><small>{exploration.environmental_place_name ? t("placeAllTimes", { place: exploration.environmental_place_name }) : t("worldwideAllTimes")}</small>
            </button>
          )}
          <button className={!livingOpen && isTimeAnchor ? "active" : ""} type="button" onClick={() => { setLivingOpen(false); startTimeWorldResearch({}); }}>
            <span>{t("timeToSpace")}</span><small>{t("worldSimultaneously")}</small>
          </button>
          <button className={livingOpen ? "active" : ""} type="button" onClick={() => setLivingOpen(true)}>
            <span>{t("livingConditions")}</span><small>{t("climateEnvironmentShort")}</small>
          </button>
        </nav>
        <header>
          <div>
            <small>{livingOpen ? t("livingHeader") : isEnvironmentAnchor ? t("natureSearchHeader") : isSpaceAnchor ? (exploration.focus_entity ? t("placeEventLinksHeader") : t("placeHistoryHeader")) : isEventAnchor ? t("eventContextHeader") : t("worldAtTimeHeader")}</small>
            <h2>{livingOpen ? `${exploration.place_name} · ${yearLabel(exploration.time_focus_year)}` : isEnvironmentAnchor ? exploration.query : isSpaceAnchor ? exploration.place_name : isEventAnchor ? exploration.focus_entity?.canonical_name : yearLabel(exploration.time_focus_year)}</h2>
          </div>
          <span className="coverage">{livingOpen ? `${livingCount} ${t(livingCount === 1 ? "finding" : "findings")}` : isEnvironmentAnchor ? `${environmentalSearch?.count ?? 0} ${t((environmentalSearch?.count ?? 0) === 1 ? "event" : "events")}` : `${t("coverage")} ${results?.coverage?.level ? coverageLabel(results.coverage.level) : "–"}`}</span>
        </header>
        {research && (
          <p className="research-state">
            {t("research")}: {RESEARCH_STATUS_LABELS[research.status] ?? research.status} ·{" "}
            {research.discovered_assertions === 0
              ? t("noNewStatements")
              : `${research.discovered_assertions} ${t(research.discovered_assertions === 1 ? "newStatement" : "newStatements")}`}
          </p>
        )}
        {resolutionMessage && <p className="resolution-state">{resolutionMessage}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="cards" ref={cardsRef}>
          {livingOpen ? (
            <LivingConditions conditions={livingConditions} />
          ) : isEnvironmentAnchor ? (
            <EnvironmentalSearchResults search={environmentalSearch} onEventSelect={pivotToEnvironmentalEvent} />
          ) : isSpaceAnchor ? (
            <>
              <PlaceTimeline timeline={timeline} onMomentSelect={pivotToTime} />
              <HistoricalProcesses data={historicalProcesses} />
              <div className="section-heading nearby-heading">
                <h3>{exploration.focus_entity ? t("verifiedPlaceLinks") : t("placesNearby")}</h3><span>{results?.count ?? 0} {t("entries")}</span>
              </div>
              {results?.assertions?.map((assertion) => <AssertionCard key={assertion.id} assertion={assertion} />)}
              <AssertionRelations relations={results?.assertion_relations} />
              {!loading && results?.count === 0 && <p className="empty">{t("noPlaces")}</p>}
            </>
          ) : isEventAnchor ? (
            <EventDossier
              dossier={eventDossier}
              view={eventView}
              onViewChange={setEventView}
              timeWorld={timeWorld}
              onMomentSelect={pivotToTime}
              onPlaceSelect={pivotToPlace}
            />
          ) : (
            <>
              <HistoricalProcesses data={historicalProcesses} />
              <TimeWorld timeWorld={timeWorld} onPlaceSelect={pivotToPlace} />
            </>
          )}
        </div>
      </aside>
      {legalOpen && <LegalNotice onClose={() => setLegalOpen(false)} />}
    </main>
  );
}
