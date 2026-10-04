import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { fmtDate, riskChips } from "../lib/format.js";
import { casesTable, dataTable, emptyState, jobsTable, kpi, newAuditAction } from "./components.js";

export async function render({ user, onLeave }) {
  const kpis = h("section", { class: "kpis" });
  const running = h("div");
  function paint(o) {
    const k = o.kpis;
    const queued = k.jobs_active - k.jobs_running;
    mount(kpis,
      kpi(k.cases_active, "Casos activos", `${k.cases_total} en total`),
      kpi(k.audits_sealed, "Auditorías selladas"),
      kpi(k.open_total, "Hallazgos abiertos", riskChips(k.open_by_risk)),
      kpi(k.jobs_active, "Ejecuciones activas", queued > 0 ? `${queued} en cola` : null));
    mount(running, jobsTable(o.active_jobs, { empty: emptyState("No hay ejecuciones en curso.", newAuditAction(user)) }));
  }
  const o = await api("/system/overview");
  paint(o);
  const timer = setInterval(async () => {
    try {
      paint(await api("/system/overview"));
    } catch {
      // keep the last figures on screen; the next refresh retries
    }
  }, 10000);
  onLeave(() => clearInterval(timer));
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Inicio"), newAuditAction(user)),
    kpis,
    h("section", { class: "card" }, h("h2", {}, "En curso"), running),
    h("section", { class: "card" }, h("h2", {}, "Casos recientes"), casesTable(o.recent_cases, user)),
    h("section", { class: "card" }, h("h2", {}, "Actividad reciente"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Caso", cell: (e) => h("a", { href: `#/cases/${encodeURIComponent(e.case_id)}/timeline` }, e.case_name) },
      { title: "Evento", cell: (e) => e.event_type },
      { title: "Descripción", cell: (e) => e.description },
    ], o.recent_events, { empty: "Sin actividad todavía." })));
}
