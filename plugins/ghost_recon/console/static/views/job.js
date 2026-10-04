// Ejecución: header with its actions, phase bar, live activity feed (SSE), "Hasta ahora" counters and, once it ends,
// the agent's summary, seal state, deliverables, tokens and the technical log.
import { api, ApiError } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, safeHref, sealCheckChip, secondsSince } from "../lib/format.js";
import { latestGuard } from "../lib/latest.js";
import { copyButton, kpi } from "./components.js";
import { openExportDialog } from "./export.js";

const FEED_MAX = 500;
const FINDING_KINDS = ["exception", "anomaly", "finding", "question"];

// Phase states come from where the run got to: while it runs the latest phase event wins over a possibly stale
// job.phase. A run that ended badly marks where it stopped with its own state and a text label (not colour alone).
const STOP_LABEL = { failed: "fallida", cancelled: "cancelada", orphaned: "interrumpida" };

function phaseStates(job, lastSeen) {
  const ids = job.phases.map((p) => p.id);
  if (job.status === "succeeded") return ids.map(() => "done");
  const reached = job.active ? ids.indexOf(lastSeen || job.phase) : Math.max(ids.indexOf(job.phase), ids.indexOf(lastSeen));
  const stop = job.status === "failed" ? "failed" : "stopped";
  return ids.map((_, i) => {
    if (i < reached) return "done";
    if (i > reached) return "pending";
    return job.active ? "current" : stop;
  });
}

function phaseBar(job, lastSeen) {
  const states = phaseStates(job, lastSeen);
  return h("ol", { class: "phases", "aria-label": "Fases" }, job.phases.map((p, i) => h("li",
    { class: `phase ${states[i]}`, "aria-current": states[i] === "current" ? "step" : null },
    states[i] === "failed" || states[i] === "stopped" ? `${p.label} (${STOP_LABEL[job.status] || "detenida"})` : p.label)));
}

function feedItem(e) {
  return h("li", { class: `feed-item kind-${e.kind} level-${e.level}` },
    h("time", { datetime: e.ts }, e.ts ? new Date(e.ts).toLocaleTimeString("es") : ""),
    h("span", { class: "feed-title" }, e.title),
    e.detail ? h("small", { class: "feed-detail" }, e.detail) : null);
}

function counters(progress) {
  if (!progress) return h("p", { class: "muted" }, "Los contadores aparecen en cuanto el agente abre el caso.");
  const f = progress.findings || {};
  const byKind = FINDING_KINDS.filter((k) => f[k]).map((k) => `${f[k]} ${label.findingKind(k)}`).join(" · ");
  return h("div", { class: "kpis" },
    kpi(progress.evidence, "Evidencia registrada"),
    kpi(progress.findings_total, "Hallazgos", byKind || "ninguno"),
    kpi(progress.criteria, "Criterios"),
    kpi(progress.research_notes, "Notas de investigación"));
}

function tokensText(t) {
  if (!t || !t.total) return "—";
  const n = (v) => Number(v || 0).toLocaleString("es");
  return `${n(t.total)} (entrada ${n(t.input)} · salida ${n(t.output)})`;
}

function exportPackage(job, user) {
  if (!job.case_id) return "—";
  const button = h("button", { class: "btn ghost small", type: "button" }, "Exportar resultados (.zip)");
  const note = h("span", { class: "download-note", role: "status" });
  button.addEventListener("click", async () => {
    note.textContent = "";
    note.classList.remove("error");
    try {
      const detail = await api(`/cases/${encodeURIComponent(job.case_id)}`);
      openExportDialog({ caseId: job.case_id, caseName: detail.case.name, audits: detail.audits, user });
    } catch (err) {
      note.textContent = err instanceof ApiError ? err.message : "No se pudo conectar con la consola.";
      note.classList.add("error");
    }
  });
  return [button, note];
}

function outcome(job, user) {
  if (job.active) return null;
  const a = job.last_audit;
  return h("section", { class: "card" }, h("h2", {}, "Resultado"),
    job.error ? h("div", { class: "error" }, job.error) : null,
    job.result_text ? h("pre", { class: "result" }, job.result_text) : h("p", { class: "muted" }, "El agente no dejó un resumen."),
    h("dl", { class: "kv" },
      h("dt", {}, "Última auditoría"), h("dd", {}, a ? [`${a.seq} · ${label.auditStatus(a.status)} `, sealCheckChip(a)] : "—"),
      h("dt", {}, "Entregables"), h("dd", {}, a && job.case_id
        ? h("a", { href: `#/cases/${encodeURIComponent(job.case_id)}/audits` }, `${a.reports} en ${a.seq}`) : "—"),
      h("dt", {}, "Paquete de resultados"), h("dd", {}, exportPackage(job, user)),
      h("dt", {}, "Tokens"), h("dd", {}, tokensText(job.tokens))));
}

function technicalLog(jobId) {
  const pre = h("pre", { class: "log" }, "Cargando…");
  const box = h("details", { class: "card" }, h("summary", {}, "Log técnico"), pre);
  box.addEventListener("toggle", async () => {
    if (!box.open) return;
    try {
      const data = await api(`/jobs/${jobId}/log`);
      pre.textContent = (data.log || "(el agente no escribió en su salida de error)")
        + (data.runner_log ? `\n\n--- runner ---\n${data.runner_log}` : "");
    } catch (err) {
      pre.textContent = `No se pudo cargar: ${err.message}`;
    }
  });
  return box;
}

export async function render({ params, user, onLeave }) {
  const jobId = Number(params[0]);
  let job = await api(`/jobs/${jobId}`);
  let lastSeen = null;
  const guard = latestGuard();
  let cancelError = null;
  const notice = h("div");
  const feed = h("ol", { class: "feed" }, h("li", { class: "feed-empty muted" }, "Esperando la primera actividad del agente…"));
  const head = h("div");
  const bar = h("div");
  const progressBox = h("div");
  const result = h("div");
  const duration = h("span");

  function tick() {
    duration.textContent = fmtDuration(job.active ? secondsSince(job.started_at || job.created_at) : job.duration_s);
  }

  function actions() {
    const items = [];
    if (user.role === "admin" && job.active) {
      const cancel = h("button", { class: "btn danger", type: "button" }, "Cancelar");
      cancel.addEventListener("click", async () => {
        if (!window.confirm("¿Cancelar esta ejecución? La auditoría a medio hacer queda abierta, sin sellar.")) return;
        cancel.disabled = true;
        try {
          const cancelled = (await api(`/jobs/${jobId}/cancel`, { method: "POST" })).job;
          guard.next();
          cancelError = null;
          job = cancelled;
          paint();
        } catch (err) {
          cancelError = err.message;
          await refresh();
          paint();
        }
      });
      items.push(cancel);
    }
    if (cancelError) items.push(h("span", { class: "error inline", role: "alert" }, `No se pudo cancelar: ${cancelError}`));
    items.push(job.resume ? copyButton(job.resume.terminal, "Continuar en terminal")
      : h("button", { class: "btn ghost", type: "button", disabled: true, title: "Aparece cuando el agente informa su sesión." }, "Continuar en terminal"));
    const chatHref = job.resume ? safeHref(job.resume.chat_url) : null;
    if (chatHref) {
      items.push(h("a", { class: "btn ghost", href: chatHref, target: "_blank", rel: "noopener noreferrer" }, "Continuar en chat"));
    }
    return items;
  }

  function paint() {
    const where = job.case_id
      ? h("a", { href: `#/cases/${encodeURIComponent(job.case_id)}` }, job.case_name || job.case_id) : job.folder_name;
    mount(head, h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, `${COMMAND_LABEL[job.command] || job.command} · #${job.id}`),
        h("p", { class: "muted" }, where, ` · lanzada por ${job.launched_by} el ${fmtDate(job.created_at)} · `,
          jobChip(job.status), " ", duration)),
      h("div", { class: "actions" }, actions())));
    tick();
    mount(bar, phaseBar(job, lastSeen));
    mount(progressBox, counters(job.progress));
    mount(result, outcome(job, user));
  }

  function addEvents(items) {
    if (!items.length) return;
    const placeholder = feed.querySelector(".feed-empty");
    if (placeholder) placeholder.remove();
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
    for (const e of items) {
      if (e.kind === "phase" && e.phase) lastSeen = e.phase;
      feed.append(feedItem(e));
    }
    while (feed.children.length > FEED_MAX) feed.firstElementChild.remove();
    if (atBottom) feed.scrollTop = feed.scrollHeight;
  }

  // Never throws; an older response that lands after a newer one is dropped.
  async function refresh() {
    const token = guard.next();
    try {
      const fresh = await api(`/jobs/${jobId}`);
      if (!guard.isLatest(token)) return;
      job = fresh;
      mount(notice, null);
    } catch (err) {
      if (guard.isLatest(token)) mount(notice, h("p", { class: "notice" }, `No se pudo actualizar la ejecución: ${err.message}`));
      return;
    }
    paint();
  }

  const first = await api(`/jobs/${jobId}/events`, { query: { after: 0 } });
  addEvents(first.items);
  paint();
  const timers = [setInterval(tick, 1000)];
  let source = null;
  if (job.active) {
    source = new EventSource(`/api/v1/jobs/${jobId}/events/stream?after=${first.last_seq}`);
    source.addEventListener("event", (msg) => {
      const e = JSON.parse(msg.data);
      addEvents([e]);
      if (e.kind === "phase") mount(bar, phaseBar(job, lastSeen));
    });
    source.addEventListener("status", () => { refresh(); });
    source.addEventListener("end", () => {
      source.close();
      refresh();
    });
    timers.push(setInterval(() => { if (job.active) refresh(); }, 5000));
  }
  onLeave(() => {
    timers.forEach(clearInterval);
    if (source) source.close();
  });
  return h("div", { class: "page" }, head, notice, bar,
    h("div", { class: "grid-2" },
      h("section", { class: "card" }, h("h2", {}, "Actividad"), feed),
      h("section", { class: "card" }, h("h2", {}, "Hasta ahora"), progressBox)),
    result, technicalLog(jobId));
}
