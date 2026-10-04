// Launch panel shared by the "+ Nueva auditoría" wizard and the Re-run / Review dialogs of the case page: options,
// the original context.md, the operator's notes and the exact command from POST /jobs/preview (the same plan the
// launch stores), then "Lanzar en segundo plano" or "Copiar comando".
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { COMMAND_LABEL, fmtBytes, shortHash } from "../lib/format.js";
import { copyText, debounce, field, modal } from "./components.js";

const MAX_NOTES = 20000;

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

function contextBlock(context) {
  if (!context) return h("p", { class: "muted" }, "La carpeta no tiene context.md.");
  return h("div", {},
    h("p", { class: "muted" }, `context.md original (solo lectura) · ${fmtBytes(context.size)} · SHA-256 `,
      h("span", { class: "mono", title: context.sha256 }, shortHash(context.sha256))),
    h("pre", { class: "context-text" }, context.truncated ? `${context.text}\n…` : context.text));
}

/** command: new-open-case | rerun-case | review-case; inspect: GET /fs/inspect of the folder; onLaunched(job). */
export function launchPanel({ command, folder, inspect, onLaunched }) {
  const withOptions = command === "new-open-case";
  const defaults = inspect.defaults || {};
  const name = h("input", { type: "text", maxlength: "120", value: defaults.name || "" });
  const currency = h("input", { type: "text", maxlength: "3", class: "short", value: defaults.currency || "USD" });
  const lang = h("select", {}, [["es", "Español"], ["en", "Inglés"]].map(([value, text]) =>
    h("option", { value, selected: value === defaults.lang }, text)));
  const notes = h("textarea", { rows: "6", maxlength: String(MAX_NOTES),
    placeholder: "Declaraciones o criterios del operador. El agente los registra como criterio (CRIT-nn) con tu usuario, nunca como hechos." });
  const counter = h("small", { class: "muted" }, `0 / ${MAX_NOTES}`);
  const cmd = h("pre", { class: "cmd" }, "Preparando el comando…");
  const notice = h("div");
  const launch = h("button", { class: "btn", type: "button", disabled: true }, "Lanzar en segundo plano");
  const copy = h("button", { class: "btn ghost", type: "button", disabled: true }, "Copiar comando");
  let preview = null;

  const body = () => ({ command, folder, notes: notes.value,
    ...(withOptions ? { name: name.value, currency: currency.value, lang: lang.value } : {}) });

  async function refresh() {
    try {
      preview = await api("/jobs/preview", { method: "POST", body: body() });
      cmd.textContent = preview.display;
      mount(notice, preview.queue_note ? h("p", { class: "notice" }, preview.queue_note) : null);
      launch.disabled = false;
      copy.disabled = Boolean(preview.notes);
      copy.title = preview.notes ? "Con notas adicionales, lanza desde la consola: el archivo de contexto se crea al lanzar." : "";
    } catch (err) {
      preview = null;
      cmd.textContent = "—";
      mount(notice, problem(err.message));
      launch.disabled = true;
      copy.disabled = true;
    }
  }

  const later = debounce(refresh, 300);
  for (const el of [name, currency, notes]) el.addEventListener("input", later);
  lang.addEventListener("change", refresh);
  notes.addEventListener("input", () => { counter.textContent = `${notes.value.length} / ${MAX_NOTES}`; });
  launch.addEventListener("click", async () => {
    launch.disabled = true;
    launch.textContent = "Lanzando…";
    try {
      onLaunched((await api("/jobs", { method: "POST", body: body() })).job);
    } catch (err) {
      mount(notice, problem(err.message));
      launch.disabled = false;
      launch.textContent = "Lanzar en segundo plano";
    }
  });
  copy.addEventListener("click", async () => {
    if (!preview) return;
    copy.textContent = (await copyText(preview.display)) ? "Copiado ✓" : "No se pudo copiar";
    setTimeout(() => { copy.textContent = "Copiar comando"; }, 1800);
  });
  refresh();
  return h("div", { class: "launch" },
    withOptions ? h("div", { class: "grid-3" },
      field("Nombre del caso", name), field("Moneda (ISO-4217)", currency), field("Idioma de los entregables", lang)) : null,
    h("h3", {}, "Contexto"),
    contextBlock(inspect.context),
    field("Notas adicionales (opcional)", notes, "Markdown. Se guardan junto a los resultados del caso, nunca entre la evidencia."),
    counter,
    h("h3", {}, "Comando exacto"),
    cmd,
    notice,
    h("div", { class: "actions" }, launch, copy));
}

/** Re-run / Review from the case page: inspects the case folder, then shows the launch panel in a dialog. */
export async function openLaunchDialog({ command, folder, title }) {
  const content = h("div", {}, h("p", { class: "muted" }, "Revisando la carpeta del caso…"));
  const dialog = modal(`${COMMAND_LABEL[command] || command} · ${title}`, content, { wide: true });
  try {
    const inspect = await api("/fs/inspect", { query: { path: folder } });
    const warnings = inspect.warnings.filter((w) => w.code !== "sealed_case");
    mount(content,
      warnings.length ? h("ul", { class: "warnings" }, warnings.map((w) => h("li", {}, w.text))) : null,
      launchPanel({ command, folder: inspect.path, inspect, onLaunched: (job) => {
        dialog.close();
        window.location.hash = `#/jobs/${job.id}`;
      } }));
  } catch (err) {
    mount(content, problem(err.message));
  }
}
