import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { jobsTable } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/jobs`);
  return h("section", { class: "card" }, jobsTable(data.items, {
    showCase: false, empty: "Este caso todavía no tiene ejecuciones lanzadas desde la consola. Usa Re-run o Review arriba." }));
}
