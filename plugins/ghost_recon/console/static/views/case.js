import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";

export async function render({ params }) {
  const detail = await api(`/cases/${encodeURIComponent(params[0])}`);
  return h("div", { class: "page" }, h("h1", {}, detail.case.name), h("p", { class: "muted mono" }, detail.case.id));
}
