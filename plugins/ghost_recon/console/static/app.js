// Console bootstrap: hash router, session bootstrap and the application shell (top bar + sidebar).
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import * as caseView from "./views/case.js";
import * as cases from "./views/cases.js";
import { errorState } from "./views/components.js";
import * as home from "./views/home.js";
import * as login from "./views/login.js";
import * as system from "./views/system.js";

const state = { user: null };

const ROUTES = [
  { re: /^\/login$/, view: login, public: true },
  { re: /^\/$/, view: home, nav: "home" },
  { re: /^\/cases$/, view: cases, nav: "cases" },
  { re: /^\/cases\/([^/]+)(?:\/([a-z]+))?$/, view: caseView, nav: "cases" },
  { re: /^\/system$/, view: system, nav: "system" },
];

const NAV = [
  { id: "home", label: "Inicio", href: "#/" },
  { id: "cases", label: "Casos", href: "#/cases" },
  { id: "jobs", label: "Ejecuciones", soon: "Disponible en H2" },
  { id: "system", label: "Sistema", href: "#/system" },
];

async function ensureSession() {
  if (state.user) return true;
  try {
    const me = await api("/auth/me");
    state.user = me.user;
    setCsrf(me.csrf);
    return true;
  } catch {
    return false;
  }
}

async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } finally {
    state.user = null;
    setCsrf(null);
    window.location.hash = "#/login";
  }
}

function shell(navId) {
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  const root = h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      h("input", { class: "search", type: "search", placeholder: "Búsqueda entre casos (disponible en H3)", disabled: true, "aria-label": "Buscar" }),
      h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
    h("nav", { class: "sidebar", "aria-label": "Secciones" }, NAV.map((n) => (n.soon
      ? h("span", { class: "nav-item soon", title: n.soon }, n.label)
      : h("a", { class: n.id === navId ? "nav-item active" : "nav-item", href: n.href, "aria-current": n.id === navId ? "page" : null }, n.label)))),
    main);
  return { root, main };
}

function onLogin(data) {
  state.user = data.user;
  setCsrf(data.csrf);
  window.location.hash = "#/";
}

async function render() {
  const path = window.location.hash.replace(/^#/, "") || "/";
  const route = ROUTES.find((r) => r.re.test(path)) || ROUTES[1];
  const params = (path.match(route.re) || []).slice(1).map((p) => (p === undefined ? undefined : decodeURIComponent(p)));
  const app = document.getElementById("app");
  app.classList.remove("boot");
  if (route.public) {
    mount(app, await route.view.render({ params, onLogin }));
    return;
  }
  if (!(await ensureSession())) {
    window.location.hash = "#/login";
    return;
  }
  const { root, main } = shell(route.nav);
  mount(app, root);
  mount(main, h("p", { class: "muted" }, "Cargando…"));
  try {
    mount(main, await route.view.render({ params, user: state.user }));
  } catch (err) {
    mount(main, errorState(err));
  }
}

window.addEventListener("hashchange", render);
render();
