import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";

export async function render({ onLogin, notice }) {
  const user = h("input", { id: "login-user", name: "username", autocomplete: "username", required: true, autofocus: true });
  const pass = h("input", { id: "login-pass", name: "password", type: "password", autocomplete: "current-password", required: true });
  const msg = h("p", { class: "login-msg", role: "alert" });
  const submit = h("button", { class: "btn", type: "submit" }, "Entrar");
  const form = h("form", {
    class: "login-card",
    onsubmit: async (event) => {
      event.preventDefault();
      submit.disabled = true;
      msg.textContent = "";
      try {
        onLogin(await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } }));
      } catch (err) {
        msg.textContent = err.message;
      } finally {
        submit.disabled = false;
      }
    },
  },
  h("span", { class: "brand", "aria-label": "Ghost Recon" }),
  h("h1", {}, "Consola"),
  notice ? h("p", { class: "notice", role: "status" }, notice) : null,
  h("label", { for: "login-user" }, "Usuario"), user,
  h("label", { for: "login-pass" }, "Contraseña"), pass,
  msg, submit);
  return h("div", { class: "login-page" }, form);
}
