import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { latestGuard } from "../lib/latest.js";
import { casesTable, debounce, errorState, newAuditAction } from "./components.js";

const RISK_OPTIONS = [["", "Cualquier riesgo"], ["any", "Con hallazgos abiertos"], ["critical", "Riesgo crítico abierto"],
  ["high", "Riesgo alto abierto"], ["medium", "Riesgo medio abierto"], ["low", "Riesgo bajo abierto"]];

export async function render({ user }) {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const risk = h("select", { "aria-label": "Riesgo abierto" },
    RISK_OPTIONS.map(([value, text]) => h("option", { value }, text)));
  const box = h("div");
  const guard = latestGuard();
  async function load() {
    const token = guard.next();
    try {
      const items = (await api("/cases", { query: { q: q.value, status: status.value, risk: risk.value } })).items;
      if (!guard.isLatest(token)) return;
      const filtered = Boolean(q.value || status.value || risk.value);
      mount(box, casesTable(items, user, filtered ? { empty: "Ningún caso coincide con los filtros." } : {}));
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  risk.addEventListener("change", load);
  await load();
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Casos"), newAuditAction(user)),
    h("div", { class: "filters" }, q, status, risk),
    h("section", { class: "card" }, box));
}
