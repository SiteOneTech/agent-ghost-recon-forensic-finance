import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { casesTable, debounce, errorState, newAuditAction } from "./components.js";

export async function render({ user }) {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const box = h("div");
  async function load() {
    try {
      const items = (await api("/cases", { query: { q: q.value, status: status.value } })).items;
      const filtered = Boolean(q.value || status.value);
      mount(box, casesTable(items, user, filtered ? { empty: "Ningún caso coincide con los filtros." } : {}));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  await load();
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Casos"), newAuditAction(user)),
    h("div", { class: "filters" }, q, status),
    h("section", { class: "card" }, box));
}
