// "+ Nueva auditoría" in three steps: pick an evidence folder inside the case roots, review what it holds, then set
// the options and context notes and launch (the launch panel shows the exact command first).
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, COMMAND_LABEL, fmtBytes, shortHash } from "../lib/format.js";
import { dataTable, debounce, emptyState, errorState } from "./components.js";
import { latestGuard } from "../lib/latest.js";
import { launchPanel } from "./launch.js";

const STEPS = ["Carpeta", "Revisión previa", "Opciones y lanzamiento"];

function stepper(current) {
  return h("ol", { class: "steps" }, STEPS.map((text, i) =>
    h("li", { class: i === current ? "current" : i < current ? "done" : null, "aria-current": i === current ? "step" : null },
      `${i + 1}. ${text}`)));
}

function caseMark(entry) {
  if (!entry.case) return chip("nueva", "info");
  return entry.case.sealed ? chip("caso existente · sellado", "ok", entry.case.id) : chip("caso existente", "muted", entry.case.id);
}

function filesText(entry) {
  return `${entry.capped ? "más de " : ""}${entry.files} archivos`;
}

function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}

function back(onclick) {
  return h("button", { class: "btn ghost", type: "button", onclick }, "← Atrás");
}

export async function render({ user, onLeave }) {
  const title = h("h1", {}, "Nueva auditoría");
  if (user.role !== "admin") {
    return h("div", { class: "page" }, title, emptyState("Solo los administradores lanzan auditorías."));
  }
  const roots = await api("/fs/roots");
  if (!roots.items.length) {
    return h("div", { class: "page" }, title, h("section", { class: "card" },
      h("h2", {}, "Falta configurar las carpetas de casos"),
      h("p", {}, roots.hint),
      h("p", { class: "muted" }, "Las evidencias se copian primero (por RustDesk o SFTP) a esa carpeta de la máquina dedicada; "
        + "la consola solo muestra lo que está dentro de las carpetas configuradas.")));
  }
  const page = h("div", { class: "page" });
  const search = h("input", { type: "search", placeholder: "Buscar una carpeta por nombre…", "aria-label": "Buscar carpetas" });
  const box = h("div");
  const stepOne = h("section", { class: "card" }, h("div", { class: "filters" }, search), box);
  let browsing = null; // folder shown in step 1; null = the list of roots
  const guard = latestGuard(); // browse, search and inspect share one box: only the newest request may paint
  let left = false;
  onLeave(() => { left = true; guard.next(); });

  function folderRow(entry, { root = false } = {}) {
    const open = h("button", { class: "open", type: "button", onclick: () => browse(entry.path) }, entry.name);
    return h("li", { class: "folder" }, open,
      entry.case !== undefined ? caseMark(entry) : null,
      entry.files !== undefined ? h("span", { class: "meta" }, filesText(entry)) : null,
      root && entry.free_bytes ? h("span", { class: "meta" }, `${fmtBytes(entry.free_bytes)} libres`) : null,
      root ? null : h("button", { class: "btn small", type: "button", onclick: () => review(entry.path) }, "Elegir"));
  }

  function crumbs(list) {
    const items = [h("button", { type: "button", onclick: () => browse(null) }, "Carpetas de casos")];
    for (const c of list) items.push(h("span", { class: "sep" }, "›"), h("button", { type: "button", onclick: () => browse(c.path) }, c.name));
    return h("nav", { class: "crumbs", "aria-label": "Ruta" }, items);
  }

  async function browse(path) {
    browsing = path;
    const token = guard.next();
    mount(page, title, stepper(0), stepOne);
    mount(box, h("p", { class: "muted" }, "Cargando…"));
    if (!path) {
      mount(box, h("p", { class: "muted" }, "Elige la carpeta de casos y, dentro, la carpeta de evidencia del caso."),
        h("ul", { class: "folders" }, roots.items.map((r) => folderRow(r, { root: true }))));
      return;
    }
    try {
      const data = await api("/fs/list", { query: { path } });
      if (!guard.isLatest(token)) return;
      const here = data.path !== data.root
        ? h("div", { class: "here" }, h("span", {}, `Carpeta actual: ${data.name} · ${filesText(data)}`), caseMark(data),
          h("button", { class: "btn", type: "button", onclick: () => review(data.path) }, "Elegir esta carpeta"))
        : null;
      mount(box, crumbs(data.breadcrumb), here,
        data.items.length ? h("ul", { class: "folders" }, data.items.map((e) => folderRow(e))) : emptyState("No hay subcarpetas."));
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }

  search.addEventListener("input", debounce(async () => {
    if (left) return;
    const q = search.value.trim();
    if (q.length < 2) {
      browse(browsing);
      return;
    }
    const token = guard.next();
    try {
      const data = await api("/fs/search", { query: { q } });
      if (!guard.isLatest(token)) return;
      const note = data.truncated ? "Hay más resultados: afina la búsqueda."
        : data.timed_out ? "La búsqueda se detuvo a los 3 segundos: afina el nombre." : data.items.length === 1 ? "1 resultado" : `${data.items.length} resultados`;
      mount(box, h("p", { class: "muted" }, note),
        data.items.length ? h("ul", { class: "folders" }, data.items.map((e) => folderRow(e))) : emptyState("Ninguna carpeta coincide."));
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }, 300));

  async function review(path) {
    const token = guard.next();
    const content = h("div", {}, h("p", { class: "muted" }, "Revisando la carpeta…"));
    mount(page, title, stepper(1), content);
    let info;
    try {
      info = await api("/fs/inspect", { query: { path } });
    } catch (err) {
      if (!guard.isLatest(token)) return;
      mount(content, errorState(err), h("div", { class: "wizard-actions" }, back(() => browse(browsing))));
      return;
    }
    if (!guard.isLatest(token)) return;
    const command = info.suggested_command;
    const c = info.case;
    mount(content,
      h("section", { class: "card" }, h("h2", {}, info.name), kv([
        ["Carpeta", h("span", { class: "mono" }, info.path)],
        ["Archivos", `${info.capped ? "más de " : ""}${info.files} · ${fmtBytes(info.size)}`],
        ["ZIP", String(info.zips)],
        ["Imágenes", String(info.images)],
        ["context.md", info.context ? h("span", { class: "mono", title: info.context.sha256 }, `sí · SHA-256 ${shortHash(info.context.sha256)}`) : "no"],
        ["Caso", c ? `${c.name} (${c.id}) · ${c.audits} auditorías, ${c.sealed} selladas` : "nuevo"],
        ["Carpeta de salida", h("span", { class: "mono" }, info.results_root)],
      ])),
      h("section", { class: "card" }, h("h2", {}, "Archivos por tipo"), dataTable([
        { title: "Tipo", cell: (r) => r.ext },
        { title: "Archivos", class: "num", cell: (r) => String(r.count) },
      ], info.by_type.slice(0, 25), { empty: "Sin archivos." })),
      info.warnings.some((w) => w.code !== "sealed_case")
        ? h("ul", { class: "warnings" }, info.warnings.filter((w) => w.code !== "sealed_case").map((w) => h("li", {}, w.text))) : null,
      command === "rerun-case"
        ? h("p", { class: "notice" }, "Esta carpeta ya es un caso con una auditoría sellada: se lanzará un Re-run, que incorpora la evidencia nueva sin tocar lo sellado.")
        : null,
      h("div", { class: "wizard-actions" }, back(() => browse(browsing)),
        h("button", { class: "btn", type: "button", onclick: () => configure(info, command) },
          command === "rerun-case" ? "Continuar con Re-run" : "Continuar")));
  }

  function configure(info, command) {
    mount(page, title, stepper(2), h("section", { class: "card" },
      h("h2", {}, `${COMMAND_LABEL[command]} · ${info.name}`),
      launchPanel({ command, folder: info.path, inspect: info, onLaunched: (job) => { window.location.hash = `#/jobs/${job.id}`; } }),
      h("div", { class: "wizard-actions" }, back(() => review(info.path)))));
  }

  await browse(null);
  return page;
}
