// Top-bar search across cases: results grouped by type, each one a link to the case tab that shows it. Esc clears;
// leaving the box closes the results.
import { api, ApiError } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { latestGuard } from "../lib/latest.js";

const GROUPS = [["case", "Casos"], ["finding", "Hallazgos"], ["evidence", "Evidencia"], ["criteria", "Criterios"]];
const LIMIT = 8;
const WAIT_MS = 250;

function results(data) {
  const groups = GROUPS.filter(([type]) => (data.items[type] || []).length);
  if (!groups.length) return h("p", { class: "muted" }, `Nada coincide con «${data.q}».`);
  return [
    groups.map(([type, title]) => h("section", { class: "search-group" }, h("h3", {}, title),
      h("ul", {}, data.items[type].map((item) => h("li", {},
        h("a", { href: `#/cases/${encodeURIComponent(item.case_id)}/${item.tab}` }, item.title),
        h("small", { class: "muted" }, `${item.case_name} · ${item.detail}`)))),
      data.more[type] ? h("p", { class: "muted" }, "Hay más resultados: afina la búsqueda.") : null)),
    data.timed_out ? h("p", { class: "muted" }, "La búsqueda se detuvo antes de recorrer todos los casos: afina el texto.") : null,
  ];
}

export function searchBox() {
  const input = h("input", { class: "search", type: "search", autocomplete: "off", "aria-label": "Buscar entre casos",
    placeholder: "Buscar entre casos: ID, hallazgo, archivo, hash…" });
  const panel = h("div", { class: "search-panel", hidden: true, role: "region", "aria-label": "Resultados de la búsqueda" });
  const wrap = h("div", { class: "search-wrap" }, input, panel);
  const guard = latestGuard();
  let timer = null;
  const hide = () => { panel.hidden = true; };

  async function run() {
    if (!wrap.isConnected) return; // the page changed while the debounce was waiting
    const q = input.value.trim();
    const token = guard.next();
    if (q.length < 2) {
      hide();
      return;
    }
    panel.hidden = false;
    mount(panel, h("p", { class: "muted" }, "Buscando…"));
    try {
      const data = await api("/search", { query: { q, limit: LIMIT } });
      if (guard.isLatest(token)) mount(panel, results(data));
    } catch (err) {
      if (guard.isLatest(token)) {
        mount(panel, h("p", { class: "error" }, err instanceof ApiError ? err.message : "No se pudo conectar con la consola."));
      }
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, WAIT_MS);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      clearTimeout(timer);
      input.value = "";
      guard.next();
      hide();
    }
  });
  input.addEventListener("focus", () => { if (input.value.trim().length >= 2 && panel.childNodes.length) panel.hidden = false; });
  wrap.addEventListener("focusout", (e) => { if (!wrap.contains(e.relatedTarget)) hide(); });
  return wrap;
}
