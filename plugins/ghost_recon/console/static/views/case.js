import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips, sealChip } from "../lib/format.js";
import { emptyState, errorState, kpi } from "./components.js";
import * as audits from "./case/audits.js";
import * as criteria from "./case/criteria.js";
import * as evidence from "./case/evidence.js";
import * as findings from "./case/findings.js";
import * as research from "./case/research.js";
import * as summary from "./case/summary.js";
import * as timeline from "./case/timeline.js";

const TABS = [
  { id: "summary", label: "Resumen", view: summary },
  { id: "audits", label: "Auditorías", view: audits },
  { id: "findings", label: "Hallazgos", view: findings },
  { id: "evidence", label: "Evidencia", view: evidence },
  { id: "criteria", label: "Criterios", view: criteria },
  { id: "research", label: "Investigación", view: research },
  { id: "timeline", label: "Cronología", view: timeline },
  { id: "jobs", label: "Ejecuciones", view: null },
];

function rerender() {
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

async function verifySeals(detail, button) {
  button.disabled = true;
  button.textContent = "Verificando…";
  try {
    for (const audit of detail.audits.filter((a) => a.status === "sealed")) {
      await api(`/cases/${encodeURIComponent(detail.case.id)}/audits/${audit.seq}/verify`, { method: "POST" });
    }
    rerender();
  } catch (err) {
    button.disabled = false;
    button.textContent = "Verificar sellos";
    button.title = `Error: ${err.message}`;
  }
}

function duplicates(stats) {
  return Object.entries(stats || {}).filter(([k]) => k.startsWith("DUP")).reduce((sum, [, v]) => sum + v, 0);
}

export async function render({ params, user }) {
  const [caseId, tabId = "summary"] = params;
  const detail = await api(`/cases/${encodeURIComponent(caseId)}`);
  const c = detail.case;
  const s = detail.summary;
  const tab = TABS.find((t) => t.id === tabId) || TABS[0];
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
  const body = h("div", { class: "tab-body" }, h("p", { class: "muted" }, "Cargando…"));
  const page = h("div", { class: "page" },
    h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, c.name),
        h("p", { class: "muted mono" }, `${c.id} · ${c.base_currency} · ${c.language} · ${c.root_path}`)),
      h("div", { class: "actions" },
        h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "▶ Re-run"),
        h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "▶ Review"),
        verify,
        h("button", { class: "btn ghost", disabled: true, title: "Disponible en H3" }, "Exportar resultados (.zip)"))),
    h("section", { class: "kpis" },
      kpi(s.audits_count, "Auditorías", sealChip(s.seal_state)),
      kpi(s.open_total, "Hallazgos abiertos", riskChips(s.open_by_risk)),
      kpi(detail.evidence.total || 0, "Evidencia", `${duplicates(detail.evidence)} duplicados`),
      kpi(fmtDate(s.last_activity), "Última actividad")),
    h("nav", { class: "tabs", "aria-label": "Secciones del caso" }, TABS.map((t) => (t.view
      ? h("a", { class: t.id === tab.id ? "tab active" : "tab", href: `#/cases/${encodeURIComponent(c.id)}/${t.id}`,
        "aria-current": t.id === tab.id ? "page" : null }, t.label)
      : h("span", { class: "tab soon", title: "Disponible en H2" }, t.label)))),
    body);
  try {
    body.replaceChildren(tab.view ? await tab.view.render({ caseId: c.id, detail, user })
      : emptyState("Las ejecuciones del caso llegan en H2."));
  } catch (err) {
    body.replaceChildren(errorState(err));
  }
  return page;
}
