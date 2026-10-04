// Results ZIP dialog: the scope (whole case or one audit), unsealed audits for admins (they go in marked as a draft),
// what goes in and why the rest stays out (GET …/export/preview), then the background build with its progress, the
// SHA-256 and the download (re-checked on click, so an expired or removed ZIP explains itself instead of opening an
// error page).
import { api, ApiError, downloadUrl } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, fmtBytes, label } from "../lib/format.js";
import { latestGuard } from "../lib/latest.js";
import { copyButton, downloadButton, field, modal } from "./components.js";

const POLL_MS = 1000;
const PENDING = ["queued", "building"];
const OFFLINE = "No se pudo conectar con la consola.";
const EXPIRED = "Este ZIP venció y ya no está disponible: vuelve a exportar.";
const GONE = "Este ZIP ya no está disponible: vuelve a exportar.";
const ROOT_FILES = ["case.json", "corpus_inventory.csv"];

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

const reason = (err) => (err instanceof ApiError ? err.message : OFFLINE);

function planView(view) {
  const held = view.skipped || []; // root files left out while a job may be rewriting them
  const roots = ROOT_FILES.filter((name) => !held.some((s) => s.path === name));
  const out = [...view.excluded.map((e) => `${e.seq}: ${e.text}`), ...held.map((s) => `${s.path}: ${s.text}`)];
  return h("div", { class: "export-plan" },
    h("h3", {}, "Entra en el ZIP"),
    h("ul", { class: "plan" }, view.audits.map((a) => h("li", {}, `${a.seq} · ${label.auditKind(a.kind)} `,
      a.draft ? chip("BORRADOR: sin sellar", "risk-medium") : chip("sellada: se verifica antes de empaquetar", "ok")))),
    h("p", { class: "muted" }, `Además: ${[...roots, "los contextos de la consola (_console/)"].join(", ")} y `
      + "EXPORT_MANIFEST.json con el SHA-256 de cada archivo. La evidencia original nunca se exporta."),
    out.length ? h("h3", {}, "Queda fuera") : null,
    out.length ? h("ul", { class: "plan" }, out.map((text) => h("li", {}, text))) : null);
}

/** «Descargar .zip»: a plain link (a large ZIP streams straight to disk), but each click first asks whether the ZIP
 *  is still there; only then the browser follows it. Otherwise the reason shows next to the link. Clicks that land
 *  while that question is open are ignored: one download per burst of clicks. */
function zipLink(row) {
  const link = h("a", { class: "btn", href: downloadUrl(`/exports/${row.id}/download`), download: row.file_name }, "Descargar .zip");
  const note = h("span", { class: "download-note error", role: "alert" });
  let checked = false;
  let checking = false;
  link.addEventListener("click", async (event) => {
    if (checked) { // the re-check below passed: this is its own click, let the browser download
      checked = false;
      return;
    }
    event.preventDefault();
    if (checking) return;
    checking = true;
    note.textContent = "";
    try {
      const fresh = await api(`/exports/${row.id}`);
      if (fresh.status === "succeeded" && fresh.available) {
        checked = true;
        link.click();
        return;
      }
      note.textContent = fresh.status === "expired" ? EXPIRED : GONE;
    } catch (err) {
      note.textContent = reason(err); // a lost session answers 401 and the console asks to log in again
    } finally {
      checking = false;
    }
  });
  return [link, note];
}

function finished(row) {
  return h("div", { class: "export-done" },
    h("p", {}, `Listo: ${row.file_name} · ${fmtBytes(row.size)} · ${row.files_total} archivos`),
    h("p", {}, "SHA-256 del ZIP: ", h("span", { class: "mono" }, row.sha256)),
    h("div", { class: "actions" },
      zipLink(row),
      downloadButton("Descargar .sha256", `/exports/${row.id}/sha256`, { small: false }),
      copyButton(row.sha256, "Copiar SHA-256")));
}

/** audits: the case's audits ({seq, kind, status}); seq preselects one audit (the per-audit ZIP buttons). */
export function openExportDialog({ caseId, caseName, audits, user, seq = null }) {
  const base = `/cases/${encodeURIComponent(caseId)}`;
  const admin = user.role === "admin";
  const scope = h("select", {}, h("option", { value: "" }, "Caso completo"),
    audits.map((a) => h("option", { value: a.seq, selected: a.seq === seq },
      `Solo ${a.seq} · ${label.auditKind(a.kind)} · ${label.auditStatus(a.status)}`)));
  const unsealed = h("input", { type: "checkbox" });
  const plan = h("div", {}, h("p", { class: "muted" }, "Calculando qué entra en el ZIP…"));
  const status = h("div", { role: "status" });
  const start = h("button", { class: "btn", type: "button", disabled: true }, "Exportar");
  const guard = latestGuard();
  let touched = false; // until the admin changes it, the checkbox shows the configured default
  let timer = null;
  let closed = false;
  const { dialog } = modal(`Exportar resultados · ${caseName}`, h("div", {},
    field("Alcance", scope),
    admin ? h("label", { class: "check" }, unsealed, "Incluir auditorías abiertas (salen marcadas como borrador)") : null,
    plan, status, h("div", { class: "actions" }, start)), { wide: true });
  dialog.addEventListener("close", () => {
    closed = true;
    guard.next();
    clearTimeout(timer);
  });

  const body = () => ({ ...(scope.value ? { scope: "audit", seq: scope.value } : { scope: "case" }),
    ...(admin && touched ? { include_unsealed: unsealed.checked } : {}) });
  const controls = (disabled) => {
    for (const el of [start, scope, unsealed]) el.disabled = disabled;
  };

  async function preview() {
    const token = guard.next();
    start.disabled = true;
    mount(status);
    try {
      const view = await api(`${base}/export/preview`, { query: body() });
      if (!guard.isLatest(token)) return;
      unsealed.checked = view.include_unsealed;
      mount(plan, planView(view));
      start.disabled = false;
    } catch (err) {
      if (guard.isLatest(token)) mount(plan, problem(reason(err)));
    }
  }

  async function follow(id) {
    let row;
    try {
      row = await api(`/exports/${id}`, { background: true });
    } catch (err) {
      if (closed) return;
      mount(status, problem(`No se pudo consultar la exportación: ${reason(err)}`));
      timer = setTimeout(() => follow(id), POLL_MS * 3);
      return;
    }
    if (closed) return;
    if (PENDING.includes(row.status)) {
      const total = row.files_total || 0;
      mount(status, h("p", {}, row.status === "queued" ? "En cola…" : `Empaquetando: ${row.files_done} de ${total} archivos`),
        h("progress", { max: String(Math.max(total, 1)), value: String(row.files_done || 0) }));
      timer = setTimeout(() => follow(id), POLL_MS);
      return;
    }
    if (row.status === "succeeded") {
      mount(status, finished(row));
      return;
    }
    mount(status, problem(row.status === "expired" ? EXPIRED : row.error || "La exportación falló."));
    controls(false); // fix the cause, then try again
  }

  scope.addEventListener("change", preview);
  unsealed.addEventListener("change", () => {
    touched = true;
    preview();
  });
  start.addEventListener("click", async () => {
    controls(true);
    try {
      const created = await api(`${base}/export`, { method: "POST", body: body() });
      follow(created.export_id);
    } catch (err) {
      mount(status, problem(reason(err)));
      controls(false);
    }
  });
  preview();
}
