import { h } from "../../lib/dom.js";
import { fmtDate, label } from "../../lib/format.js";

function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}

function counts(obj, fmt = (k) => k) {
  return Object.entries(obj || {}).filter(([k]) => k !== "total").map(([k, v]) => `${fmt(k)}: ${v}`).join(" · ");
}

export async function render({ detail }) {
  const c = detail.case;
  const last = detail.summary.last_audit;
  return h("div", { class: "grid-2" },
    h("section", { class: "card" }, h("h2", {}, "Caso"), kv([
      ["ID", h("span", { class: "mono" }, c.id)],
      ["Carpeta de evidencia", h("span", { class: "mono" }, c.root_path)],
      ["Carpeta de resultados", h("span", { class: "mono" }, detail.results_root)],
      ["Estado", c.status], ["Moneda", c.base_currency], ["Idioma", c.language], ["Creado", fmtDate(c.created_at)],
      ["Última auditoría", last ? `${last.seq} · ${label.auditKind(last.kind)} · ${label.auditStatus(last.status)}` : null],
    ])),
    h("section", { class: "card" }, h("h2", {}, "Contenido"), kv([
      ["Evidencia por estado", counts(detail.evidence)],
      ["Hallazgos por tipo", counts(detail.findings.by_kind, label.findingKind)],
      ["Hallazgos por estado", counts(detail.findings.by_status)],
      ["Criterios", String(detail.criteria)],
      ["Notas de investigación", String(detail.research_notes)],
    ])));
}
