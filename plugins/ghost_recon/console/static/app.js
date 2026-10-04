// Console bootstrap: hash router, session bootstrap and the application shell (top bar + sidebar).
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import * as caseView from "./views/case.js";
import * as cases from "./views/cases.js";
import { errorState } from "./views/components.js";
import * as home from "./views/home.js";
import * as job from "./views/job.js";
import * as jobs from "./views/jobs.js";
import * as login from "./views/login.js";
import * as system from "./views/system.js";
import * as users from "./views/users.js";
import * as wizard from "./views/wizard.js";

const state = { user: null };
let leaving = [];
let generation = 0;

const ROUTES = [
  { re: /^\/login$/, view: login, public: true },
  { re: /^\/$/, view: home, nav: "home" },
  { re: /^\/cases$/, view: cases, nav: "cases" },
  { re: /^\/cases\/([^/]+)(?:\/([a-z]+))?$/, view: caseView, nav: "cases" },
  { re: /^\/jobs$/, view: jobs, nav: "jobs" },
  { re: /^\/jobs\/(\d+)$/, view: job, nav: "jobs" },
  { re: /^\/system$/, view: system, nav: "system" },
  { re: /^\/system\/users$/, view: users, nav: "system" },
  { re: /^\/new$/, view: wizard, nav: null },
];

const NAV = [
  { id: "home", label: "Inicio", href: "#/" },
  { id: "cases", label: "Casos", href: "#/cases" },
  { id: "jobs", label: "Ejecuciones", href: "#/jobs" },
  { id: "system", label: "Sistema", href: "#/system" },
];

/** Views register cleanups (EventSource, timers) that run when the user navigates away. A render that was already
 *  superseded registers late: its cleanup runs at once so nothing it opened outlives it. */
function onLeaveFor(token) {
  return (fn) => {
    if (token === generation) leaving.push(fn);
    else fn();
  };
}

function leave() {
  const fns = leaving;
  leaving = [];
  for (const fn of fns) fn();
}

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
  } catch (err) {
    // 401: the session is already gone, so leaving is honest. Anything else: the cookie may still be valid.
    if (err.status !== 401) {
      document.getElementById("main").prepend(h("div", { class: "error", role: "alert" },
        `No se pudo cerrar la sesión: ${err.message}. Sigues con la sesión abierta.`));
      return;
    }
  }
  state.user = null;
  setCsrf(null);
  window.location.hash = "#/login";
}

function shell(navId) {
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  const admin = state.user.role === "admin";
  const root = h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      h("input", { class: "search", type: "search", placeholder: "Buscar entre casos", disabled: true, title: "Próximamente", "aria-label": "Buscar entre casos" }),
      admin ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría")
        : h("button", { class: "btn", disabled: true, title: "Solo los administradores lanzan auditorías." }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
    h("nav", { class: "sidebar", "aria-label": "Secciones" }, NAV.map((n) =>
      h("a", { class: n.id === navId ? "nav-item active" : "nav-item", href: n.href, "aria-current": n.id === navId ? "page" : null }, n.label))),
    main);
  return { root, main };
}

function onLogin(data) {
  state.user = data.user;
  setCsrf(data.csrf);
  window.location.hash = "#/";
}

async function render() {
  generation += 1;
  const token = generation;
  const current = () => token === generation;
  leave();
  const path = window.location.hash.replace(/^#/, "") || "/";
  const route = ROUTES.find((r) => r.re.test(path)) || ROUTES[1];
  const params = (path.match(route.re) || []).slice(1).map((p) => (p === undefined ? undefined : decodeURIComponent(p)));
  const app = document.getElementById("app");
  app.classList.remove("boot");
  if (route.public) {
    const page = await route.view.render({ params, onLogin });
    if (current()) mount(app, page);
    return;
  }
  const signedIn = await ensureSession();
  if (!current()) return;
  if (!signedIn) {
    window.location.hash = "#/login";
    return;
  }
  const { root, main } = shell(route.nav);
  mount(app, root);
  mount(main, h("p", { class: "muted" }, "Cargando…"));
  let page;
  try {
    page = await route.view.render({ params, user: state.user, onLeave: onLeaveFor(token) });
  } catch (err) {
    page = errorState(err);
  }
  if (current()) mount(main, page);
}

window.addEventListener("hashchange", render);
render();
