// Launch panel shared by the "+ Nueva auditoría" wizard and the Re-run / Review dialogs of the case page: options,
// the original context.md, the operator's notes and the exact command from POST /jobs/preview (the same plan the
// launch stores), then "Lanzar en segundo plano" or "Copiar comando".
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { COMMAND_LABEL, fmtBytes, shortHash } from "../lib/format.js";
import { latestGuard } from "../lib/latest.js";
import { copyText, debounce, field, modal } from "./components.js";

const MAX_NOTES = 20000;

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

const contextSha = (context) => (context ? context.sha256 : "none");

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
  let launching = false;
  let shown = inspect.context; // the context.md the operator is looking at
  const contextBox = h("div", {}, contextBlock(shown));
  const guard = latestGuard();

  const body = () => ({ command, folder, notes: notes.value,
    ...(withOptions ? { name: name.value, currency: currency.value, lang: lang.value } : {}) });

  // Lanzar is only enabled while the shown command is the preview of exactly what body() would launch.
  function invalidate() {
    guard.next();
    preview = null;
    launch.disabled = true;
    copy.disabled = true;
  }

  async function refresh() {
    const token = guard.next();
    try {
      const result = await api("/jobs/preview", { method: "POST", body: body() });
      if (!guard.isLatest(token)) return;
      if (contextSha(result.original_context) !== contextSha(shown)) {
        // context.md changed since it was shown: show the current one before anything can be launched with it.
        const fresh = (await api("/fs/inspect", { query: { path: folder } })).context;
        if (!guard.isLatest(token)) return; // a newer refresh owns `shown` and the box
        shown = fresh;
        mount(contextBox, h("p", { class: "notice" }, "El context.md de la carpeta cambió: esta es la versión actual."),
          contextBlock(shown));
        if (contextSha(result.original_context) !== contextSha(shown)) {
          throw new Error("El context.md de la carpeta está cambiando: espera a que termine y vuelve a intentarlo.");
        }
      }
      preview = result;
      cmd.textContent = preview.display;
      mount(notice, preview.queue_note ? h("p", { class: "notice" }, preview.queue_note) : null);
      launch.disabled = launching;
      copy.disabled = Boolean(preview.notes);
      copy.title = preview.notes ? "Con notas adicionales, lanza desde la consola: el archivo de contexto se crea al lanzar." : "";
    } catch (err) {
      if (!guard.isLatest(token)) return;
      preview = null;
      cmd.textContent = "—";
      mount(notice, problem(err.message));
      launch.disabled = true;
      copy.disabled = true;
    }
  }

  const later = debounce(refresh, 300);
  for (const el of [name, currency, notes]) el.addEventListener("input", () => { invalidate(); later(); });
  lang.addEventListener("change", () => { invalidate(); refresh(); });
  notes.addEventListener("input", () => { counter.textContent = `${notes.value.length} / ${MAX_NOTES}`; });
  launch.addEventListener("click", async () => {
    if (!preview) return;
    launching = true;
    launch.disabled = true;
    launch.textContent = "Lanzando…";
    // The context.md the operator reviewed: the server refuses the launch (409) if it changed since the preview.
    const reviewed = contextSha(preview.original_context);
    try {
      onLaunched((await api("/jobs", { method: "POST", body: { ...body(), context_sha256: reviewed } })).job);
    } catch (err) {
      launching = false;
      launch.textContent = "Lanzar en segundo plano";
      if (err.code === "context_changed") {
        invalidate();
        await refresh(); // shows the current context.md and its command
        notice.prepend(problem(err.message));
        return;
      }
      mount(notice, problem(err.message));
      launch.disabled = !preview;
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
    contextBox,
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
