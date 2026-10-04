import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { chip, fmtBytes, fmtDate, label, sealCheckChip, shortHash } from "../../lib/format.js";
import { dataTable, downloadButton, toggleDetail } from "../components.js";

const CHECK_LABEL = {
  manifest: "manifiesto", evidence_register: "registro de evidencia", model_json: "model.json", report_md: "informe MD",
  report_pdf: "informe PDF", workbook_xlsx: "workbook XLSX", validation: "validación", exceptions_export: "export de excepciones",
};

// One specific message per way a verification can fail; the counts only when files actually differ.
function sealProblem(detail) {
  const d = detail || {};
  if (d.reason === "read_error") return "No se pudo leer la carpeta de la auditoría para verificar el sello.";
  if (d.sealed === false) return "Falta el manifiesto SEALED.json o no es válido: no se puede comprobar el sello.";
  if (d.db_matches === false) return "El hash del sello registrado en la base de datos no coincide con el manifiesto de la carpeta.";
  const [modified, missing, added] = [d.modified, d.missing, d.added].map((l) => (l || []).length);
  if (modified + missing + added > 0) return `Sello alterado: ${modified} modificados, ${missing} faltantes, ${added} añadidos.`;
  return "La verificación del sello falló por una causa no identificada.";
}

async function auditDetail(caseId, audit, user) {
  const base = `/cases/${encodeURIComponent(caseId)}/audits/${audit.seq}`;
  const [d, reports] = await Promise.all([api(base), api(`${base}/reports`)]);
  const canDownload = audit.status === "sealed" || user.role === "admin";
  const broken = d.seal_check && !d.seal_check.ok ? d.seal_check.detail : null;
  return h("div", { class: "detail" },
    h("h3", {}, "Completitud"),
    h("div", { class: "checks" }, Object.entries(d.completion.checks).map(([k, ok]) =>
      chip(`${ok ? "✓" : "✗"} ${CHECK_LABEL[k] || k}`, ok ? "ok" : "risk-high"))),
    broken ? h("p", { class: "error" }, sealProblem(broken)) : null,
    h("h3", {}, "Entregables"),
    dataTable([
      // A sealed audit's deliverable is re-hashed on download; a changed file is refused here, by name.
      { title: "Archivo", cell: (r) => (canDownload
        ? downloadButton(r.name, `${base}/reports/${r.id}/download`, { title: "Descargar" }) : r.name) },
      { title: "Tipo", cell: (r) => `${r.kind} · ${r.format} · ${r.version}` },
      { title: "Tamaño", class: "num", cell: (r) => fmtBytes(r.size) },
      { title: "SHA-256", cell: (r) => h("span", { class: "mono", title: r.sha256 }, shortHash(r.sha256)) },
    ], reports.items, { empty: "Sin entregables registrados." }),
    canDownload ? null : h("p", { class: "muted" }, "Los entregables de auditorías abiertas solo los descarga un admin."));
}

export async function render({ caseId, detail, user }) {
  return h("section", { class: "card" }, dataTable([
    { title: "Auditoría", cell: (a) => h("strong", {}, a.seq) },
    { title: "Tipo", cell: (a) => label.auditKind(a.kind) },
    { title: "Estado", cell: (a) => label.auditStatus(a.status) },
    { title: "Iniciada", cell: (a) => fmtDate(a.started_at) },
    { title: "Sellada", cell: (a) => fmtDate(a.sealed_at) },
    { title: "Sello", cell: (a) => sealCheckChip(a) },
    { title: "Entregables", class: "num", cell: (a) => String(a.reports) },
  ], detail.audits, { empty: "Sin auditorías.", onRow: (a, tr) => toggleDetail(tr, () => auditDetail(caseId, a, user)) }));
}
