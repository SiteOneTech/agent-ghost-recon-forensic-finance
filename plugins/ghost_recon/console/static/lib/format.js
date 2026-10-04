// Formatting helpers shared by the views. They return text or nodes built with h(), never HTML strings.
import { h } from "./dom.js";

export const RISKS = ["critical", "high", "medium", "low"];
export const RISK_LABEL = { critical: "crítico", high: "alto", medium: "medio", low: "bajo" };
const SEAL = {
  ok: ["sello OK", "ok"],
  broken: ["sello alterado", "risk-high"],
  unverified: ["sin verificar", "info"],
  none: ["sin sellar", "muted"],
};
const AUDIT_STATUS = { open: "abierta", in_progress: "en curso", validated: "validada", sealed: "sellada", failed: "fallida" };
const AUDIT_KIND = { initial: "inicial", rerun: "re-run", review: "revisión" };
const FINDING_KIND = { exception: "excepción", anomaly: "anomalía", finding: "hallazgo", question: "pregunta" };

export const label = {
  auditStatus: (s) => AUDIT_STATUS[s] || s,
  auditKind: (k) => AUDIT_KIND[k] || k,
  findingKind: (k) => FINDING_KIND[k] || k,
};

function parse(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = parse(iso);
  return d ? d.toLocaleString("es", { dateStyle: "medium", timeStyle: "short" }) : String(iso);
}

export function fmtDay(iso) {
  if (!iso) return "—";
  const d = parse(iso);
  return d ? d.toLocaleDateString("es", { dateStyle: "medium" }) : String(iso);
}

export function fmtAmount(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  const text = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  return currency ? `${text} ${currency}` : text;
}

export function fmtBytes(value) {
  let n = Number(value) || 0;
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let i = -1;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(1)} ${units[i]}`;
}

export function chip(text, variant = "muted", title) {
  return h("span", { class: `chip ${variant}`, title }, text);
}

export function riskChip(risk, count) {
  const name = RISK_LABEL[risk] || risk;
  return chip(count === undefined ? name : `${count} ${name}`, `risk-${risk}`);
}

export function riskChips(byRisk) {
  const parts = RISKS.filter((r) => (byRisk || {})[r] > 0).map((r) => riskChip(r, byRisk[r]));
  return parts.length ? parts : [chip("ninguno", "muted")];
}

export function sealChip(state) {
  const [text, variant] = SEAL[state] || SEAL.none;
  return chip(text, variant);
}

export function sealCheckChip(audit) {
  if (audit.status !== "sealed") return chip("sin sellar", "muted");
  const check = audit.seal_check;
  if (!check) return chip("sin verificar", "info");
  const title = `verificado ${fmtDate(check.checked_at)} por ${check.checked_by || "—"}`;
  return check.ok ? chip("sello OK", "ok", title) : chip("sello alterado", "risk-high", title);
}

export function shortHash(sha) {
  return sha ? `${sha.slice(0, 12)}…` : "—";
}

// Research URLs are external content: only http(s) becomes a link (never javascript:, data:, …).
export function safeHref(url) {
  return /^https?:\/\//i.test(String(url || "")) ? String(url) : null;
}

export const COMMAND_LABEL = { "new-open-case": "Nueva auditoría", "rerun-case": "Re-run", "review-case": "Review" };
const JOB_STATUS = {
  queued: ["en cola", "info"],
  running: ["en curso", "info"],
  succeeded: ["terminada", "ok"],
  failed: ["fallida", "risk-high"],
  cancelled: ["cancelada", "muted"],
  orphaned: ["interrumpida", "risk-medium"],
};
export const JOB_STATUS_OPTIONS = Object.entries(JOB_STATUS).map(([value, [text]]) => [value, text]);

export function jobChip(status) {
  const [text, variant] = JOB_STATUS[status] || [status, "muted"];
  return chip(text, variant, status === "orphaned" ? "El proceso de la ejecución se detuvo sin registrar su final." : undefined);
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours} h ${minutes} min`;
  return minutes ? `${minutes} min ${total % 60} s` : `${total % 60} s`;
}

export function secondsSince(iso) {
  const start = parse(iso || "");
  return start ? (Date.now() - start.getTime()) / 1000 : null;
}
