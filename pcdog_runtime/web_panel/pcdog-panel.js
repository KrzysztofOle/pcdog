"use strict";

// Lekkie parametry operacyjne panelu; nie wymagają builda ani zewnętrznej sieci.
const CONFIG = Object.freeze({ pollingIntervalMs: 5000, eventsLimit: 25, requestTimeoutMs: 4000 });
let refreshInFlight = false;
const VIEWS = { status: "Status", history: "Historia", network: "Sieć", settings: "Ustawienia" };

function selectView(focus = false) {
  const requested = window.location.hash.slice(1);
  if (requested === "content") return;
  const view = Object.hasOwn(VIEWS, requested) ? requested : "status";
  document.querySelectorAll("[data-view]").forEach(section => { section.hidden = section.dataset.view !== view; });
  document.querySelectorAll(".navigation a").forEach(link => {
    if (link.getAttribute("href") === "#" + view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = "PcDog — " + VIEWS[view];
  text("view-title", VIEWS[view]);
  if (focus) document.getElementById("content").focus();
}

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
  text("state-reliability", !state.power_led_reliable || !state.hdd_activity_reliable ? "Uwaga: co najmniej jeden sygnał jest niewiarygodny." : "");
}

function renderUnavailableState(reason) {
  setBadge("pc-state", "UNKNOWN");
  setBadge("power-led", "UNKNOWN");
  setBadge("hdd-activity", "UNKNOWN");
  setBadge("pcdog-state", "UNKNOWN");
  text("state-updated-at", "brak danych");
  text("state-reliability", "Brak wiarygodnego odczytu.");
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
    const row = document.createElement("li"); row.className = "card";
    row.textContent = "Brak zapisanych zdarzeń."; list.append(row);
    text("events-detail", "Brak zapisanych zdarzeń."); return;
  }
  const names = { PC_STATE_CHANGED: "Zmiana stanu PC", POWER_LED_CHANGED: "Zmiana POWER LED", HDD_ACTIVITY_CHANGED: "Zmiana aktywności HDD" };
  for (const event of [...events].reverse()) {
    const row = document.createElement("li"); row.className = "card";
    const heading = document.createElement("div"); heading.className = "event-heading";
    const title = document.createElement("h2"); title.textContent = names[event.event_type] || event.event_type;
    const time = document.createElement("time"); time.className = "detail"; time.dateTime = event.timestamp_utc; time.textContent = browserTime(event.timestamp_utc);
    heading.append(title, time);
    const change = document.createElement("p"); change.className = "event-change";
    change.textContent = (event.old_value || "brak danych") + " → " + (event.new_value || "brak danych");
    const source = document.createElement("p"); source.className = "detail"; source.textContent = "Źródło: " + event.source;
    row.append(heading, change, source);
    list.append(row);
  }
  text("events-detail", `Wyświetlono ${events.length} ostatnich zdarzeń · najnowsze na początku.`);
}

function renderEventsUnavailable() {
  const list = document.getElementById("events-list"); list.replaceChildren();
  const row = document.createElement("li"); row.className = "card";
  row.textContent = "Historia zdarzeń jest obecnie niedostępna."; list.append(row);
  text("events-detail", "Błąd historii nie wpływa na bieżący stan.");
}

function renderNetwork(network) {
  const list = document.getElementById("network-list"); list.replaceChildren();
  if (network.status !== "AVAILABLE" || !network.interfaces.length) {
    const message = document.createElement("p"); message.className = "card";
    message.textContent = "Dane sieci są niedostępne. Nie oznacza to rozłączenia.";
    list.append(message); text("network-summary", "Dane sieci są niedostępne."); return;
  }
  text("network-summary", network.interfaces.map(item => item.name + ": " + (item.connection || item.state || "brak danych")).join(" · "));
  for (const item of network.interfaces) {
    const card = document.createElement("article"); card.className = "card";
    const title = document.createElement("h2"); title.textContent = item.name;
    const details = document.createElement("dl"); details.className = "status-list";
    for (const [label, value] of [["Typ", item.type], ["Stan NetworkManager", item.state], ["Profil połączenia", item.connection], ["Adresy IP", item.addresses.join(", ")]]) {
      const row = document.createElement("div"); const key = document.createElement("dt"); const val = document.createElement("dd");
      key.textContent = label; val.textContent = value || "brak danych"; row.append(key, val); details.append(row);
    }
    card.append(title, details); list.append(card);
  }
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const [health, state, events, network] = await Promise.allSettled([
      getJson("/api/v1/health"), getJson("/api/v1/state"), getJson(`/api/v1/events?limit=${CONFIG.eventsLimit}`),
      getJson("/api/v1/network"),
    ]);
    health.status === "fulfilled" ? renderHealth(health.value) : renderHealthUnavailable();
    state.status === "fulfilled" ? renderState(state.value) : renderUnavailableState(state.reason.message);
    events.status === "fulfilled" ? renderEvents(events.value.events) : renderEventsUnavailable();
    renderNetwork(network.status === "fulfilled" ? network.value : { status: "UNAVAILABLE", interfaces: [] });
    if (state.status === "fulfilled") text("refresh-status", `Odświeżono: ${new Date().toLocaleTimeString()}`);
  } finally {
    refreshInFlight = false;
  }
}

selectView();
window.addEventListener("hashchange", () => selectView(true));
text("browser-timezone", Intl.DateTimeFormat().resolvedOptions().timeZone);
refresh();
window.setInterval(refresh, CONFIG.pollingIntervalMs);
