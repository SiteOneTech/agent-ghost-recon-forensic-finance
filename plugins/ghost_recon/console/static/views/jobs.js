// Ejecuciones: every console job, newest first, filterable by status and case; refreshes while any is active.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { JOB_STATUS_OPTIONS } from "../lib/format.js";
import { latestGuard } from "../lib/latest.js";
import { emptyState, errorState, jobsTable, newAuditAction } from "./components.js";

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

export async function render({ user, onLeave }) {
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "active" }, "Activas (en cola o en curso)"),
    JOB_STATUS_OPTIONS.map(([value, text]) => h("option", { value }, capitalize(text))));
  const cases = (await api("/cases")).items;
  const caseFilter = h("select", { "aria-label": "Caso" }, h("option", { value: "" }, "Todos los casos"),
    cases.map((c) => h("option", { value: c.id }, c.name)));
  const box = h("div");
  let active = false;
  const guard = latestGuard();
  async function load() {
    const token = guard.next();
    try {
      const data = await api("/jobs", { query: { status: status.value, case: caseFilter.value } });
      if (!guard.isLatest(token)) return;
      active = data.items.some((j) => j.active);
      const filtered = Boolean(status.value || caseFilter.value);
      mount(box, jobsTable(data.items, { empty: filtered ? "No hay ejecuciones con estos filtros."
        : emptyState("Todavía no se ha lanzado ninguna ejecución.", newAuditAction(user)) }));
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }
  status.addEventListener("change", load);
  caseFilter.addEventListener("change", load);
  await load();
  const timer = setInterval(() => { if (active) load(); }, 5000);
  onLeave(() => clearInterval(timer));
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Ejecuciones"), newAuditAction(user)),
    h("div", { class: "filters" }, status, caseFilter),
    h("section", { class: "card" }, box));
}
