const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.detail || `HTTP ${response.status}`;
    throw new ApiError(message, response.status, body);
  }
  return body;
}

export function createExplorationContext(initial = {}) {
  return request("/exploration-contexts/", { method: "POST", body: JSON.stringify(initial) });
}

export function loadExplorationContext(id) {
  return request(`/exploration-contexts/${id}/`);
}

export function updateExplorationContext(id, patch, baseVersion) {
  return request(`/exploration-contexts/${id}/`, {
    method: "PATCH",
    body: JSON.stringify({ ...patch, base_version: baseVersion }),
  });
}

export function loadExplorationResults(id) {
  return request(`/exploration-contexts/${id}/results/`);
}

export function loadExplorationTimeline(id) {
  return request(`/exploration-contexts/${id}/timeline/`);
}

export function loadTimeWorld(id) {
  return request(`/exploration-contexts/${id}/time-world/`);
}

export function loadLivingConditions(id) {
  return request(`/exploration-contexts/${id}/living-conditions/`);
}

export function loadEnvironmentalEvents(id) {
  return request(`/exploration-contexts/${id}/environmental-events/`);
}

export function loadEventDossier(id) {
  return request(`/exploration-contexts/${id}/event-dossier/`);
}

export function resolveExplorationInput(id, query, baseVersion) {
  return request(`/exploration-contexts/${id}/resolve/`, {
    method: "POST",
    body: JSON.stringify({ query, base_version: baseVersion }),
  });
}

export function startExplorationResearch(id) {
  return request(`/exploration-contexts/${id}/research/`, { method: "POST", body: "{}" });
}

export function loadResearch(id) {
  return request(`/research/${id}/`);
}

export async function reverseGeocodePlace(latitude, longitude, language = "en") {
  const parameters = new URLSearchParams({
    format: "jsonv2",
    lat: String(latitude),
    lon: String(longitude),
    zoom: "10",
    addressdetails: "1",
    "accept-language": language,
  });
  const response = await fetch(`https://nominatim.openstreetmap.org/reverse?${parameters}`);
  if (!response.ok) return null;
  const result = await response.json();
  const address = result.address ?? {};
  const name = address.city
    || address.town
    || address.municipality
    || address.village
    || address.county
    || address.state_district
    || String(result.display_name || "").split(",")[0].trim();
  return name ? { name, displayName: result.display_name || name } : null;
}
