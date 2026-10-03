import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmtDate, safeHref } from "../../lib/format.js";
import { dataTable } from "../components.js";

function source(note) {
  const href = safeHref(note.url);
  const text = note.title || note.url || "—";
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : text;
}

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/research`);
  return h("section", { class: "card" }, dataTable([
    { title: "Fecha", cell: (n) => fmtDate(n.created_at) },
    { title: "Acción", cell: (n) => n.action },
    { title: "Consulta", cell: (n) => n.query || "—" },
    { title: "Fuente", cell: source },
    { title: "Extracto", cell: (n) => n.snippet || "—" },
    { title: "Auditoría", cell: (n) => (n.audit_id ? n.audit_id.split("/").pop() : "—") },
  ], data.items, { empty: "Sin notas de investigación." }));
}
