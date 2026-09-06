"use strict";

// Lekkie parametry operacyjne panelu; nie wymagają builda ani zewnętrznej sieci.
const CONFIG = Object.freeze({ pollingIntervalMs: 5000, eventsLimit: 25, requestTimeoutMs: 4000 });
let refreshInFlight = false;

const text = (id, value) => { document.getElementById(id).textContent = value; };
const badgeClass = (value) => {
  const known = new Set(["on", "off", "unknown", "active", "idle", "healthy", "degraded", "error"]);
  const normalized = String(value).toLowerCase();
  return `badge badge-${known.has(normalized) ? normalized : "unknown"}`;
};

function setBadge(id, value, fallback = "UNKNOWN") {
  const element = document.getElementById(id);
  const shown = value || fallback;
  element.textContent = shown;
  element.className = badgeClass(shown);
}

function browserTime(utcTimestamp) {
  const parsed = new Date(utcTimestamp);
  return Number.isNaN(parsed.getTime()) ? "brak danych" : parsed.toLocaleString();
}

async function getJson(path) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), CONFIG.requestTimeoutMs);
  try {
    const response = await fetch(path, { method: "GET", signal: controller.signal, headers: { Accept: "application/json" } });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.code || "HTTP_ERROR");
    return body;
  } finally {
    window.clearTimeout(timeout);
  }
}

function renderState(state) {
  setBadge("pc-state", state.pc_state);
  setBadge("power-led", state.power_led);
  setBadge("hdd-activity", state.hdd_activity);
  setBadge("pcdog-state", state.pcdog_state);
  text("state-updated-at", browserTime(state.updated_at_utc));
}

function renderUnavailableState(reason) {
  setBadge("pc-state", "UNKNOWN");
  setBadge("power-led", "UNKNOWN");
  setBadge("hdd-activity", "UNKNOWN");
  setBadge("pcdog-state", "UNKNOWN");
  text("state-updated-at", "brak danych");
  text("refresh-status", reason === "STATE_UNAVAILABLE" ? "Stan nie jest jeszcze dostępny." : "Nie udało się odczytać stanu PC.");
}

function renderHealth(health) {
  setBadge("api-health", health.status, "brak danych");
  text("health-detail", `GET /api/v1/health: ${health.status}`);
}

function renderHealthUnavailable() {
  setBadge("api-health", "brak danych", "brak danych");
  text("health-detail", "Endpoint health jest obecnie niedostępny.");
}

function renderEvents(events) {
  const list = document.getElementById("events-list");
  list.replaceChildren();
  if (!events.length) {
    const row = document.createElement("tr"); const cell = document.createElement("td");
    cell.colSpan = 5; cell.textContent = "Brak zapisanych zdarzeń."; row.append(cell); list.append(row); return;
  }
  for (const event of events) {
    const row = document.createElement("tr");
    for (const value of [browserTime(event.timestamp_utc), event.event_type, event.source, event.old_value, event.new_value]) {
      const cell = document.createElement("td"); cell.textContent = value || "brak danych"; row.append(cell);
    }
    list.append(row);
  }
  text("events-detail", `Wyświetlono ${events.length} ostatnich zdarzeń.`);
}

function renderEventsUnavailable() {
  const list = document.getElementById("events-list"); list.replaceChildren();
  const row = document.createElement("tr"); const cell = document.createElement("td");
  cell.colSpan = 5; cell.textContent = "Historia zdarzeń jest obecnie niedostępna."; row.append(cell); list.append(row);
  text("events-detail", "Błąd historii nie wpływa na bieżący stan.");
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const [health, state, events] = await Promise.allSettled([
      getJson("/api/v1/health"), getJson("/api/v1/state"), getJson(`/api/v1/events?limit=${CONFIG.eventsLimit}`),
    ]);
    health.status === "fulfilled" ? renderHealth(health.value) : renderHealthUnavailable();
    state.status === "fulfilled" ? renderState(state.value) : renderUnavailableState(state.reason.message);
    events.status === "fulfilled" ? renderEvents(events.value.events) : renderEventsUnavailable();
    if (state.status === "fulfilled") text("refresh-status", `Odświeżono: ${new Date().toLocaleTimeString()}`);
  } finally {
    refreshInFlight = false;
  }
}

refresh();
window.setInterval(refresh, CONFIG.pollingIntervalMs);
