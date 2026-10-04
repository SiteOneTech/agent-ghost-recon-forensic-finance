import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips, sealChip } from "../lib/format.js";
import { errorState, kpi } from "./components.js";
import * as audits from "./case/audits.js";
import * as criteria from "./case/criteria.js";
import * as evidence from "./case/evidence.js";
import * as findings from "./case/findings.js";
import * as jobs from "./case/jobs.js";
import * as research from "./case/research.js";
import * as summary from "./case/summary.js";
import * as timeline from "./case/timeline.js";
import { openExportDialog } from "./export.js";
import { openLaunchDialog } from "./launch.js";

const TABS = [
  { id: "summary", label: "Resumen", view: summary },
  { id: "audits", label: "Auditorías", view: audits },
  { id: "findings", label: "Hallazgos", view: findings },
  { id: "evidence", label: "Evidencia", view: evidence },
  { id: "criteria", label: "Criterios", view: criteria },
  { id: "research", label: "Investigación", view: research },
  { id: "timeline", label: "Cronología", view: timeline },
  { id: "jobs", label: "Ejecuciones", view: jobs },
];

function rerender() {
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

// The re-render below rebuilds the page, so verification errors are handed over to the next render().
let verifyErrors = [];

async function verifySeals(detail, button) {
  button.disabled = true;
  button.textContent = "Verificando…";
  verifyErrors = [];
  for (const audit of detail.audits.filter((a) => a.status === "sealed")) {
    try {
      await api(`/cases/${encodeURIComponent(detail.case.id)}/audits/${audit.seq}/verify`, { method: "POST" });
    } catch (err) {
      verifyErrors.push(`${audit.seq}: ${err.message}`);
    }
  }
  rerender();
}

function verifyNotice() {
  const errors = verifyErrors;
  verifyErrors = [];
  return errors.length
    ? h("div", { class: "error", role: "alert" }, `No se pudo verificar el sello (${errors.join("; ")}). El estado mostrado puede no estar al día.`)
    : null;
}

function duplicates(stats) {
  return Object.entries(stats || {}).filter(([k]) => k.startsWith("DUP")).reduce((sum, [, v]) => sum + v, 0);
}

function launchButton(text, command, theCase, user, blocked) {
  const reason = user.role !== "admin" ? "Solo los administradores lanzan ejecuciones." : blocked;
  const button = h("button", { class: "btn", type: "button", disabled: Boolean(reason), title: reason || null }, text);
  button.addEventListener("click", () => openLaunchDialog({ command, folder: theCase.root_path, title: theCase.name }));
  return button;
}

export async function render({ params, user }) {
  const [caseId, tabId = "summary"] = params;
  const detail = await api(`/cases/${encodeURIComponent(caseId)}`);
  const c = detail.case;
  const s = detail.summary;
  const tab = TABS.find((t) => t.id === tabId) || TABS[0];
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
  const exportZip = h("button", { class: "btn ghost", type: "button" }, "Exportar resultados (.zip)");
  exportZip.addEventListener("click", () => openExportDialog({ caseId: c.id, caseName: c.name, audits: detail.audits, user }));
  const notice = verifyNotice();
  const body = h("div", { class: "tab-body" }, h("p", { class: "muted" }, "Cargando…"));
  const page = h("div", { class: "page" },
    h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, c.name),
        h("p", { class: "muted mono" }, `${c.id} · ${c.base_currency} · ${c.language} · ${c.root_path}`)),
      h("div", { class: "actions" },
        launchButton("▶ Re-run", "rerun-case", c, user, null),
        launchButton("▶ Review", "review-case", c, user, s.sealed_count === 0 ? "La revisión necesita una auditoría sellada." : null),
        verify,
        exportZip)),
    notice,
    h("section", { class: "kpis" },
      kpi(s.audits_count, "Auditorías", sealChip(s.seal_state)),
      kpi(s.open_total, "Hallazgos abiertos", riskChips(s.open_by_risk)),
      kpi(detail.evidence.total || 0, "Evidencia", `${duplicates(detail.evidence)} duplicados`),
      kpi(fmtDate(s.last_activity), "Última actividad")),
    h("nav", { class: "tabs", "aria-label": "Secciones del caso" }, TABS.map((t) =>
      h("a", { class: t.id === tab.id ? "tab active" : "tab", href: `#/cases/${encodeURIComponent(c.id)}/${t.id}`,
        "aria-current": t.id === tab.id ? "page" : null }, t.label))),
    body);
  try {
    body.replaceChildren(await tab.view.render({ caseId: c.id, detail, user }));
  } catch (err) {
    body.replaceChildren(errorState(err));
  }
  return page;
}
