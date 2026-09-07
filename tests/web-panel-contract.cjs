// Test logiki UI bez przeglądarki i dodatkowych zależności: node tests/web-panel-contract.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor() { this.children = []; this.attributes = {}; this.textContent = ""; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  getAttribute(key) { return this.attributes[key]; }
  focus() { this.focused = true; }
  addEventListener() {}
}
const views = ["status", "history", "network", "settings"].map(view => {
  const element = new Element(); element.dataset = { view }; return element;
});
const links = views.map(section => {
  const element = new Element(); element.setAttribute("href", "#" + section.dataset.view); return element;
});
const elements = new Map();
const document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  createElement() { return new Element(); },
  querySelectorAll(selector) { return selector === "[data-view]" ? views : links; },
};
const window = {
  location: { hash: "#history" }, addEventListener() {},
  setInterval() {}, setTimeout() { return 1; }, clearTimeout() {},
};
const context = vm.createContext({
  document, window, Intl, AbortController,
  fetch: async () => { throw new Error("offline"); },
});
vm.runInContext(fs.readFileSync(require("node:path").join(__dirname, "../pcdog_runtime/web_panel/pcdog-panel.js"), "utf8"), context);
context.selectView();
assert.equal(views[1].hidden, false);
assert.equal(links[1].attributes["aria-current"], "page");
window.location.hash = "#network";
context.selectView(true);
assert.equal(views[2].hidden, false);
assert.equal(views[1].hidden, true);
assert.equal(document.getElementById("content").focused, true);
window.location.hash = "#invalid";
context.selectView();
assert.equal(views[0].hidden, false);
context.renderEvents([
  { timestamp_utc: "2026-09-01T12:00:00Z", event_type: "PC_STATE_CHANGED", old_value: "OFF", new_value: "ON", source: "STATE_ENGINE" },
  { timestamp_utc: "2026-09-01T13:00:00Z", event_type: "<script>", old_value: "ON", new_value: "OFF", source: "STATE_ENGINE" },
]);
assert.equal(document.getElementById("events-list").children.length, 2);
assert.equal(document.getElementById("events-list").children[0].children[0].children[0].textContent, "<script>");
context.renderEvents([]);
assert.equal(document.getElementById("events-detail").textContent, "Brak zapisanych zdarzeń.");
context.renderNetwork({ status: "UNAVAILABLE", interfaces: [] });
assert.match(document.getElementById("network-summary").textContent, /niedostępne/);
context.renderUnavailableState("STATE_UNAVAILABLE");
assert.equal(document.getElementById("pc-state").textContent, "UNKNOWN");
console.log("PASS: login shell, routes, focus, cards, empty/error states, safe text rendering");
