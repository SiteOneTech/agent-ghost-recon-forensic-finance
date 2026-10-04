import { api } from "../../lib/api.js";
import { h, mount } from "../../lib/dom.js";
import { chip, fmtBytes, label, shortHash } from "../../lib/format.js";
import { dataTable, debounce, errorState, tableExport } from "../components.js";

const PAGE = 100;

export async function render({ caseId, detail }) {
  const stats = await api(`/cases/${encodeURIComponent(caseId)}/evidence/stats`);
  const status = h("select", { "aria-label": "Estado" }, h("option", { value: "" }, "Todos los estados"),
    Object.keys(stats.statuses).filter((k) => k !== "total").map((k) => h("option", { value: k }, label.evidenceStatus(k))));
  const audit = h("select", { "aria-label": "Auditoría" }, h("option", { value: "" }, "Todas las auditorías"),
    detail.audits.filter((a) => a.kind !== "review").map((a) => h("option", { value: a.seq }, `Primera vez en ${a.seq}`)));
  const q = h("input", { type: "search", placeholder: "Buscar por ruta, nombre o hash…", "aria-label": "Buscar evidencia" });
  const box = h("div");
  const more = h("button", { class: "btn ghost", type: "button", hidden: true }, "Cargar más");
  const filters = () => ({ status: status.value, audit: audit.value, q: q.value });
  let rows = [];
  let cursor = null;
  const columns = [
    { title: "Ruta", cell: (e) => h("span", { class: "mono" }, e.path) },
    { title: "Tipo", cell: (e) => e.ext || "—" },
    { title: "Tamaño", class: "num", cell: (e) => fmtBytes(e.size) },
    { title: "Estado", cell: (e) => chip(label.evidenceStatus(e.status), e.status.startsWith("DUP") ? "risk-medium" : "muted") },
    { title: "Bloque", cell: (e) => e.block },
    { title: "Auditoría", cell: (e) => (e.first_audit_id ? e.first_audit_id.split("/").pop() : "—") },
    { title: "SHA-256", cell: (e) => h("span", { class: "mono", title: e.sha256 }, shortHash(e.sha256)) },
  ];
  async function load(reset) {
    more.disabled = true; // a double click must not append the same page twice
    try {
      if (reset) {
        rows = [];
        cursor = null;
      }
      const data = await api(`/cases/${encodeURIComponent(caseId)}/evidence`,
        { query: { ...filters(), limit: PAGE, cursor } });
      rows = rows.concat(data.items);
      cursor = data.next_cursor;
      mount(box, h("p", { class: "muted" }, `${rows.length} de ${data.total} archivos`),
        dataTable(columns, rows, { empty: "No hay evidencia con estos filtros." }));
      more.hidden = !cursor;
    } catch (err) {
      mount(box, errorState(err));
    } finally {
      more.disabled = false;
    }
  }
  status.addEventListener("change", () => load(true));
  audit.addEventListener("change", () => load(true));
  q.addEventListener("input", debounce(() => load(true), 250));
  more.addEventListener("click", () => load(false));
  await load(true);
  return h("section", { class: "card" },
    h("div", { class: "chips" }, Object.entries(stats.blocks).map(([k, v]) => chip(`${k}: ${v}`, "muted"))),
    h("div", { class: "filters" }, status, audit, q), tableExport(caseId, "evidence", filters), box, more);
}
