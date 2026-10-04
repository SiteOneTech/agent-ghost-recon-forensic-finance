// Shared view pieces: KPI tiles, tables with expandable rows, empty/error states, the cases and jobs tables, form
// fields, dialogs and copy-to-clipboard.
import { download } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, riskChips, sealChip } from "../lib/format.js";

export function kpi(value, title, extra) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-value" }, value === null || value === undefined ? "—" : String(value)),
    h("div", { class: "kpi-title" }, title),
    extra ? h("div", { class: "kpi-extra" }, extra) : null);
}

/** Empty state: a sentence plus, optionally, the action that fills it (buttons or links; nulls are skipped). */
export function emptyState(text, ...actions) {
  const items = actions.flat().filter(Boolean);
  return h("div", { class: "empty" }, h("p", {}, text), items.length ? h("div", { class: "empty-actions" }, items) : null);
}

export function errorState(err) {
  return h("div", { class: "error", role: "alert" }, `No se pudo cargar: ${(err && err.message) || err}`);
}

/** columns: [{ title, cell(row) -> node|string|array, class? }]; opts: { empty (text or node), onRow(row, tr) }. */
export function dataTable(columns, rows, opts = {}) {
  if (!rows || !rows.length) return opts.empty instanceof Node ? opts.empty : emptyState(opts.empty || "Sin datos.");
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

/** The "+ Nueva auditoría" action for admins; null for viewers. */
export function newAuditAction(user) {
  return user && user.role === "admin" ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría") : null;
}

export function casesTable(rows, user, { empty } = {}) {
  return dataTable([
    { title: "Caso", cell: (r) => h("a", { href: `#/cases/${encodeURIComponent(r.id)}` }, r.name) },
    { title: "Última auditoría", cell: (r) => (r.last_audit
      ? `${r.last_audit.seq} · ${label.auditStatus(r.last_audit.status)} · ${fmtDate(r.last_audit.started_at)}` : "—") },
    { title: "Abiertos", cell: (r) => riskChips(r.open_by_risk) },
    { title: "Sello", cell: (r) => sealChip(r.seal_state) },
    { title: "Última actividad", cell: (r) => fmtDate(r.last_activity) },
  ], rows, { empty: empty || emptyState("Todavía no hay casos.", newAuditAction(user)) });
}

export function jobsTable(rows, { showCase = true, empty = "Sin ejecuciones." } = {}) {
  return dataTable([
    { title: "#", cell: (j) => h("a", { href: `#/jobs/${j.id}` }, `#${j.id}`) },
    { title: "Orden", cell: (j) => COMMAND_LABEL[j.command] || j.command },
    showCase ? { title: "Caso o carpeta", cell: (j) => (j.case_id
      ? h("a", { href: `#/cases/${encodeURIComponent(j.case_id)}` }, j.case_name || j.case_id) : j.folder_name) } : null,
    { title: "Estado", cell: (j) => jobChip(j.status) },
    { title: "Fase", cell: (j) => j.phase_label || "—" },
    { title: "Lanzada por", cell: (j) => j.launched_by },
    { title: "Inicio", cell: (j) => fmtDate(j.started_at || j.created_at) },
    { title: "Duración", class: "num", cell: (j) => fmtDuration(j.duration_s) },
  ].filter(Boolean), rows, { empty });
}

/** A button that downloads an API attachment in place; a refusal is shown in `note` (or after the button). */
export function downloadButton(text, path, { query = () => ({}), note = null, title = null, small = true } = {}) {
  const status = note || h("span", { class: "download-note", role: "status" });
  const button = h("button", { class: small ? "btn ghost small" : "btn ghost", type: "button", title }, text);
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    status.classList.remove("error");
    try {
      await download(path, query());
    } catch (err) {
      status.textContent = err.message;
      status.classList.add("error");
    } finally {
      button.disabled = false;
    }
  });
  return note ? button : h("span", { class: "download" }, button, status);
}

/** "CSV" / "XLSX" of a case table: what the table shows, with its current filters (`filters()` → query). */
export function tableExport(caseId, table, filters = () => ({})) {
  const note = h("span", { class: "download-note", role: "status" });
  const path = (fmt) => `/cases/${encodeURIComponent(caseId)}/${table}.${fmt}`;
  return h("div", { class: "table-export" }, h("span", { class: "muted" }, "Exportar con los filtros activos:"),
    downloadButton("CSV", path("csv"), { query: filters, note, title: "CSV en UTF-8 (se abre en Excel con acentos)" }),
    downloadButton("XLSX", path("xlsx"), { query: filters, note, title: "Libro de Excel con metadatos Ghost Recon" }),
    note);
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

let fieldSeq = 0;

/** A labelled form control (the label points at the control). */
export function field(text, control, hint) {
  fieldSeq += 1;
  if (!control.id) control.id = `field-${fieldSeq}`;
  return h("div", { class: "field" }, h("label", { for: control.id }, text), control,
    hint ? h("small", { class: "muted" }, hint) : null);
}

/** Copy to the clipboard; falls back to a hidden textarea where the async clipboard API is unavailable. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h("textarea", { class: "copy-fallback", readonly: true }, text);
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function copyButton(text, labelText = "Copiar") {
  const button = h("button", { class: "btn ghost", type: "button" }, labelText);
  button.addEventListener("click", async () => {
    button.textContent = (await copyText(text)) ? "Copiado ✓" : "No se pudo copiar";
    setTimeout(() => { button.textContent = labelText; }, 1800);
  });
  return button;
}

/** A modal <dialog>; closing it (✕, Esc or navigating away) removes it from the page. */
export function modal(title, body, { wide = false } = {}) {
  const close = h("button", { class: "btn ghost small", type: "button", "aria-label": "Cerrar" }, "✕");
  const dialog = h("dialog", { class: wide ? "modal wide" : "modal", "aria-label": title },
    h("div", { class: "modal-head" }, h("h2", {}, title), close), body);
  dialog.addEventListener("close", () => dialog.remove());
  close.addEventListener("click", () => dialog.close());
  window.addEventListener("hashchange", () => dialog.close(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, close: () => dialog.close() };
}
