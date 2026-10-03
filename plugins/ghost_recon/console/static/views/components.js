// Shared view pieces: KPI tiles, data tables with expandable rows, empty/error states, the cases table, debounce.
import { h } from "../lib/dom.js";
import { fmtDate, label, riskChips, sealChip } from "../lib/format.js";

export function kpi(value, title, extra) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-value" }, value === null || value === undefined ? "—" : String(value)),
    h("div", { class: "kpi-title" }, title),
    extra ? h("div", { class: "kpi-extra" }, extra) : null);
}

export function emptyState(text) {
  return h("div", { class: "empty" }, text);
}

export function errorState(err) {
  return h("div", { class: "error", role: "alert" }, `No se pudo cargar: ${(err && err.message) || err}`);
}

/** columns: [{ title, cell(row) -> node|string|array, class? }]; opts: { empty, onRow(row, tr) }. */
export function dataTable(columns, rows, opts = {}) {
  if (!rows || !rows.length) return emptyState(opts.empty || "Sin datos.");
  const head = h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.class, scope: "col" }, c.title))));
  const body = h("tbody");
  for (const row of rows) {
    const tr = h("tr", {}, columns.map((c) => h("td", { class: c.class }, c.cell(row))));
    if (opts.onRow) {
      tr.classList.add("clickable");
      tr.tabIndex = 0;
      const open = () => opts.onRow(row, tr);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    }
    body.append(tr);
  }
  return h("table", { class: "data" }, head, body);
}

/** Toggle a full-width detail row under `tr`; `build` is async and returns the detail node. */
export async function toggleDetail(tr, build) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail-row")) {
    next.remove();
    return;
  }
  const cell = h("td", { colspan: String(tr.children.length) }, "Cargando…");
  tr.after(h("tr", { class: "detail-row" }, cell));
  try {
    cell.replaceChildren(await build());
  } catch (err) {
    cell.replaceChildren(errorState(err));
  }
}

export function casesTable(rows) {
  return dataTable([
    { title: "Caso", cell: (r) => h("a", { href: `#/cases/${encodeURIComponent(r.id)}` }, r.name) },
    { title: "Última auditoría", cell: (r) => (r.last_audit
      ? `${r.last_audit.seq} · ${label.auditStatus(r.last_audit.status)} · ${fmtDate(r.last_audit.started_at)}` : "—") },
    { title: "Abiertos", cell: (r) => riskChips(r.open_by_risk) },
    { title: "Sello", cell: (r) => sealChip(r.seal_state) },
    { title: "Última actividad", cell: (r) => fmtDate(r.last_activity) },
  ], rows, { empty: "Todavía no hay casos. Se crean con /new-open-case (desde la consola en H2)." });
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
