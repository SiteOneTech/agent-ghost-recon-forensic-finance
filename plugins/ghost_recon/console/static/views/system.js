import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { chip, fmtDate } from "../lib/format.js";
import { dataTable } from "./components.js";

export async function render({ user }) {
  const doc = await api("/system/doctor");
  const parts = [
    h("h1", {}, "Sistema"),
    h("p", { class: "muted" }, `Consola ${doc.console.version} · ${doc.console.host}:${doc.console.port}`),
    h("section", { class: "card" }, h("h2", {}, doc.ok ? "Diagnóstico: todo en orden" : "Diagnóstico: requiere atención"),
      dataTable([
        { title: "Estado", cell: (c) => (c.ok ? chip("OK", "ok") : chip("revisar", "risk-high")) },
        { title: "Comprobación", cell: (c) => c.check },
        { title: "Detalle", cell: (c) => c.detail },
      ], doc.checks)),
  ];
  if (user.role === "admin") {
    const log = await api("/system/audit-log", { query: { limit: 200 } });
    parts.push(h("section", { class: "card" }, h("h2", {}, "Registro de la consola"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Usuario", cell: (e) => e.username || "—" },
      { title: "Acción", cell: (e) => e.action },
      { title: "Objetivo", cell: (e) => e.target || "—" },
      { title: "IP", cell: (e) => e.ip || "—" },
    ], log.items, { empty: "Sin registros." })));
  }
  return h("div", { class: "page" }, parts);
}
