import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips } from "../lib/format.js";
import { casesTable, dataTable, kpi } from "./components.js";

export async function render() {
  const o = await api("/system/overview");
  const k = o.kpis;
  return h("div", { class: "page" },
    h("h1", {}, "Inicio"),
    h("section", { class: "kpis" },
      kpi(k.cases_active, "Casos activos", `${k.cases_total} en total`),
      kpi(k.audits_sealed, "Auditorías selladas"),
      kpi(k.open_total, "Hallazgos abiertos", riskChips(k.open_by_risk)),
      kpi(k.jobs_active, "Ejecuciones activas", "disponible en H2")),
    h("section", { class: "card" }, h("h2", {}, "Casos recientes"), casesTable(o.recent_cases)),
    h("section", { class: "card" }, h("h2", {}, "Actividad reciente"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Caso", cell: (e) => h("a", { href: `#/cases/${encodeURIComponent(e.case_id)}/timeline` }, e.case_name) },
      { title: "Evento", cell: (e) => e.event_type },
      { title: "Descripción", cell: (e) => e.description },
    ], o.recent_events, { empty: "Sin actividad todavía." })));
}
