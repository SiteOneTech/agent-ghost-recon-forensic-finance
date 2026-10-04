import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { dataTable, tableExport } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/criteria`);
  return h("section", { class: "card" }, tableExport(caseId, "criteria"), dataTable([
    { title: "ID", cell: (c) => h("strong", { class: "mono" }, c.id) },
    { title: "Fecha", cell: (c) => c.date || "—" },
    { title: "Autor", cell: (c) => c.author },
    { title: "Texto (literal)", cell: (c) => c.text },
    { title: "Estado", cell: (c) => c.status },
    { title: "Auditoría", cell: (c) => (c.audit_id ? c.audit_id.split("/").pop() : "—") },
  ], data.items, { empty: "Sin criterios registrados." }));
}
