import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { casesTable, debounce, errorState } from "./components.js";

export async function render() {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const box = h("div");
  async function load() {
    try {
      mount(box, casesTable((await api("/cases", { query: { q: q.value, status: status.value } })).items));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  await load();
  return h("div", { class: "page" }, h("h1", {}, "Casos"), h("div", { class: "filters" }, q, status),
    h("section", { class: "card" }, box));
}
