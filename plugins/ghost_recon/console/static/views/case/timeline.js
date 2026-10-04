import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmtDate } from "../../lib/format.js";
import { dataTable, tableExport } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/timeline`);
  return h("section", { class: "card" }, tableExport(caseId, "timeline"), dataTable([
    { title: "Fecha", cell: (e) => fmtDate(e.ts) },
    { title: "Evento", cell: (e) => e.event_type },
    { title: "Auditoría", cell: (e) => (e.audit_id ? e.audit_id.split("/").pop() : "—") },
    { title: "Actor", cell: (e) => e.actor },
    { title: "Descripción", cell: (e) => e.description },
  ], data.items, { empty: "Sin eventos." }));
}
