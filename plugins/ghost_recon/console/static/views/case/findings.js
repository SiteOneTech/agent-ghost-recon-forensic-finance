import { api } from "../../lib/api.js";
import { h, mount } from "../../lib/dom.js";
import { fmtAmount, fmtDate, riskChip } from "../../lib/format.js";
import { dataTable, debounce, errorState, toggleDetail } from "../components.js";

function select(name, options, selected) {
  return h("select", { "aria-label": name }, options.map(([value, text]) => h("option", { value, selected: value === selected }, text)));
}

function change(entry) {
  if (typeof entry.change === "string") return entry.change;
  return Object.entries(entry.change || {}).map(([k, v]) => `${k} → ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
}

function findingDetail(f) {
  const refs = Array.isArray(f.evidence_refs) ? f.evidence_refs : [];
  const history = Array.isArray(f.history) ? f.history : [];
  return h("div", { class: "detail" },
    f.description ? h("p", {}, f.description) : null,
    h("dl", { class: "kv" },
      h("dt", {}, "Siguiente evidencia"), h("dd", {}, f.next_evidence || "—"),
      h("dt", {}, "Quién aporta"), h("dd", {}, f.owner || "—"),
      h("dt", {}, "Contraparte / entidad"), h("dd", {}, [f.counterparty, f.entity].filter(Boolean).join(" · ") || "—"),
      h("dt", {}, "Evidencia"), h("dd", {}, refs.length
        ? h("ul", {}, refs.map((r) => h("li", { class: "mono" }, typeof r === "string" ? r : JSON.stringify(r)))) : "—")),
    h("h3", {}, "Historia entre auditorías"),
    h("ol", { class: "history" }, history.map((e) =>
      h("li", {}, `${fmtDate(e.ts)} · ${e.audit_id ? e.audit_id.split("/").pop() : "—"} · ${change(e)}`))));
}

export async function render({ caseId }) {
  const kind = select("Tipo", [["", "Todos los tipos"], ["exception", "Excepciones"], ["anomaly", "Anomalías"],
    ["finding", "Hallazgos"], ["question", "Preguntas"]], "");
  const risk = select("Riesgo", [["", "Todos los riesgos"], ["critical", "Crítico"], ["high", "Alto"], ["medium", "Medio"],
    ["low", "Bajo"]], "");
  const status = select("Estado", [["", "Todos los estados"], ["open", "Abiertos"], ["closed", "Cerrados"],
    ["downgraded", "Degradados"], ["upgraded", "Elevados"], ["superseded", "Sustituidos"]], "open");
  const q = h("input", { type: "search", placeholder: "Buscar por ID, título, contraparte…", "aria-label": "Buscar hallazgos" });
  const box = h("div");
  async function load() {
    try {
      const data = await api(`/cases/${encodeURIComponent(caseId)}/findings`,
        { query: { kind: kind.value, risk: risk.value, status: status.value, q: q.value } });
      mount(box, dataTable([
        { title: "ID", cell: (f) => h("strong", { class: "mono" }, f.id) },
        { title: "Título", cell: (f) => f.title },
        { title: "Monto", class: "num", cell: (f) => fmtAmount(f.amount, f.currency) },
        { title: "Riesgo", cell: (f) => riskChip(f.risk) },
        { title: "Confianza", cell: (f) => f.confidence },
        { title: "Etiqueta", cell: (f) => f.label },
        { title: "Estado", cell: (f) => f.status },
        { title: "Quién aporta", cell: (f) => f.owner || "—" },
      ], data.items, { empty: "No hay hallazgos con estos filtros.", onRow: (f, tr) => toggleDetail(tr, async () => findingDetail(f)) }));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  for (const el of [kind, risk, status]) el.addEventListener("change", load);
  q.addEventListener("input", debounce(load, 250));
  await load();
  return h("section", { class: "card" }, h("div", { class: "filters" }, kind, risk, status, q), box);
}
