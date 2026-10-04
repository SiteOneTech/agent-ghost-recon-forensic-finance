// Sistema › Usuarios y tokens (admin): accounts, password resets, enable/disable, roles and API tokens. The server
// applies the same rules as the CLI; your own account cannot be disabled or demoted from here.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, fmtDate } from "../lib/format.js";
import { copyButton, dataTable, emptyState, field, modal } from "./components.js";

function passwordPair() {
  const pass = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: true });
  const again = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: true });
  return { pass, again, fields: [field("Contraseña (mínimo 10 caracteres)", pass), field("Repite la contraseña", again)] };
}

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

export async function render({ user }) {
  const title = h("div", { class: "page-head" }, h("h1", {}, "Usuarios y tokens"), h("a", { class: "btn ghost", href: "#/system" }, "← Sistema"));
  if (user.role !== "admin") {
    return h("div", { class: "page" }, title, emptyState("Solo los administradores gestionan usuarios y tokens."));
  }
  const msg = h("div");
  const usersBox = h("div");
  const tokensBox = h("div");

  async function act(fn) {
    try {
      await fn();
      await reload();
    } catch (err) {
      mount(msg, problem(err.message));
    }
  }

  function resetDialog(username) {
    const { pass, again, fields } = passwordPair();
    const error = h("div");
    const form = h("form", {}, h("p", { class: "muted" }, `Las sesiones abiertas de ${username} se cerrarán.`), fields, error,
      h("div", { class: "actions" }, h("button", { class: "btn", type: "submit" }, "Guardar contraseña")));
    const dialog = modal(`Restablecer contraseña · ${username}`, form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/users/${encodeURIComponent(username)}/password`, { method: "POST", body: { password: pass.value, password_confirm: again.value } });
        dialog.close();
        await reload();
      } catch (err) {
        mount(error, problem(err.message));
      }
    });
  }

  function rowActions(u) {
    const self = u.username === user.username;
    const reset = h("button", { class: "btn ghost small", type: "button", onclick: () => resetDialog(u.username) }, "Restablecer contraseña");
    const toggle = h("button", { class: "btn ghost small", type: "button", disabled: self,
      title: self ? "No puedes deshabilitar tu propio usuario." : null }, u.disabled ? "Habilitar" : "Deshabilitar");
    toggle.addEventListener("click", () => {
      if (!u.disabled && !window.confirm(`¿Deshabilitar a ${u.username}? Sus sesiones se cerrarán.`)) return;
      act(() => api(`/users/${encodeURIComponent(u.username)}/${u.disabled ? "enable" : "disable"}`, { method: "POST" }));
    });
    const other = u.role === "admin" ? "viewer" : "admin";
    const role = h("button", { class: "btn ghost small", type: "button", disabled: self,
      title: self ? "No puedes cambiar tu propio rol." : null }, other === "admin" ? "Hacer admin" : "Hacer viewer");
    role.addEventListener("click", () => act(() => api(`/users/${encodeURIComponent(u.username)}/role`, { method: "POST", body: { role: other } })));
    return h("div", { class: "actions" }, reset, toggle, role);
  }

  function usersTable(items) {
    return dataTable([
      { title: "Usuario", cell: (u) => h("strong", {}, u.username) },
      { title: "Rol", cell: (u) => u.role },
      { title: "Estado", cell: (u) => (u.disabled ? chip("deshabilitado", "muted") : chip("activo", "ok")) },
      { title: "Último acceso", cell: (u) => fmtDate(u.last_login_at) },
      { title: "Acciones", cell: rowActions },
    ], items, { empty: "Sin usuarios." });
  }

  function newUserForm() {
    const username = h("input", { type: "text", autocomplete: "off", maxlength: "32", required: true });
    const role = h("select", {}, h("option", { value: "viewer" }, "viewer (solo lectura)"), h("option", { value: "admin" }, "admin"));
    const { pass, again, fields } = passwordPair();
    const form = h("form", { class: "inline-form" }, field("Usuario", username), field("Rol", role), fields,
      h("button", { class: "btn", type: "submit" }, "Crear usuario"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      act(async () => {
        await api("/users", { method: "POST", body: { username: username.value, role: role.value, password: pass.value, password_confirm: again.value } });
        form.reset();
      });
    });
    return form;
  }

  function tokensTable(items) {
    return dataTable([
      { title: "ID", class: "num", cell: (t) => String(t.id) },
      { title: "Nombre", cell: (t) => t.name },
      { title: "Usuario", cell: (t) => t.username },
      { title: "Token", cell: (t) => h("span", { class: "mono" }, `grt_${t.prefix}_…`) },
      { title: "Creado", cell: (t) => fmtDate(t.created_at) },
      { title: "Último uso", cell: (t) => fmtDate(t.last_used_at) },
      { title: "Estado", cell: (t) => (t.revoked ? chip("revocado", "muted") : chip("activo", "ok")) },
      { title: "", cell: (t) => (t.revoked ? null : h("button", { class: "btn ghost small", type: "button", onclick: () => {
        if (window.confirm(`¿Revocar el token «${t.name}»? Quien lo use dejará de tener acceso.`)) {
          act(() => api(`/tokens/${t.id}/revoke`, { method: "POST" }));
        }
      } }, "Revocar")) },
    ], items, { empty: "Sin tokens de API." });
  }

  function newTokenForm(users) {
    const owner = h("select", {}, users.filter((u) => !u.disabled).map((u) => h("option", { value: u.username }, u.username)));
    const name = h("input", { type: "text", maxlength: "80", required: true, placeholder: "p. ej. web-app" });
    const form = h("form", { class: "inline-form" }, field("Usuario", owner), field("Nombre del token", name),
      h("button", { class: "btn", type: "submit" }, "Crear token"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      act(async () => {
        const created = await api("/tokens", { method: "POST", body: { username: owner.value, name: name.value } });
        form.reset();
        modal("Token creado", h("div", {},
          h("p", {}, "Cópialo ahora: no se volverá a mostrar. Se envía en la cabecera «Authorization: Bearer <token>»."),
          h("p", { class: "token-once" }, created.token),
          copyButton(created.token, "Copiar token")));
      });
    });
    return form;
  }

  async function reload() {
    mount(msg);
    const [users, tokens] = await Promise.all([api("/users"), api("/tokens")]);
    mount(usersBox, usersTable(users.items));
    mount(tokensBox, tokensTable(tokens.items), h("h3", {}, "Crear token"), newTokenForm(users.items));
  }

  await reload();
  return h("div", { class: "page" }, title, msg,
    h("section", { class: "card" }, h("h2", {}, "Usuarios"), usersBox, h("h3", {}, "Crear usuario"), newUserForm()),
    h("section", { class: "card" }, h("h2", {}, "Tokens de API"), tokensBox));
}
