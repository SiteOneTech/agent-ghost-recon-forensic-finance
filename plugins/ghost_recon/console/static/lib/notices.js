// Browser notices when a job ends or fails while the console is open. Opt-in twice: the "Avisarme al terminar"
// toggle (remembered in this browser) and the browser's own permission. One watcher per page polls the newest jobs
// and announces each one that ended since the previous poll (also one that started and ended in between).
import { api } from "./api.js";
import { h } from "./dom.js";
import { COMMAND_LABEL } from "./format.js";

const KEY = "gr.notify";
const POLL_MS = 15000;
const RECENT = 50;
const OUTCOME = { succeeded: "terminó", failed: "falló", cancelled: "se canceló", orphaned: "se interrumpió" };
let known = null; // job id -> whether it was active at the previous poll
let timer = null;
let polling = false;
let owner = null; // who the watcher runs for: the choice is remembered per user
let generation = 0; // bumped on stop/restart: a poll that started before it drops its result

function supported() {
  return "Notification" in window && window.isSecureContext;
}

function wanted() {
  try {
    return localStorage.getItem(`${KEY}:${owner}`) === "1";
  } catch {
    return false; // storage blocked: the toggle cannot be remembered, so notices stay off
  }
}

function remember(on) {
  try {
    localStorage.setItem(`${KEY}:${owner}`, on ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
}

function on() {
  return Boolean(owner) && supported() && wanted() && Notification.permission === "granted";
}

function announce(job) {
  try {
    const notice = new Notification(`Ghost Recon · ejecución #${job.id} ${OUTCOME[job.status] || job.status}`, {
      body: `${COMMAND_LABEL[job.command] || job.command} · ${job.case_name || job.folder_name}`, tag: `gr-job-${job.id}` });
    notice.onclick = () => {
      window.focus();
      window.location.hash = `#/jobs/${job.id}`;
      notice.close();
    };
  } catch {
    // this platform cannot build notifications (e.g. an illegal constructor): the job stays marked as announced
  }
}

async function poll() {
  if (!on()) {
    known = null;
    return;
  }
  if (polling) return;
  polling = true;
  const mine = generation;
  try {
    const jobs = (await api("/jobs", { query: { limit: RECENT }, background: true })).items;
    if (mine !== generation || !on()) return; // signed out, another user or switched off while the request ran
    const before = known;
    known = new Map(jobs.map((j) => [j.id, j.active])); // recorded first: a failing notice is never repeated
    if (before) {
      for (const job of jobs) if (!job.active && before.get(job.id) !== false) announce(job);
    }
  } catch (err) {
    if (err.status === 401) stopWatcher(); // the session is gone: stop asking
    // otherwise the server is restarting: the next poll tries again
  } finally {
    if (mine === generation) polling = false;
  }
}

export function startWatcher(username) {
  if (timer && owner === username) return;
  stopWatcher();
  owner = username;
  timer = setInterval(poll, POLL_MS);
  poll();
}

export function stopWatcher() {
  clearInterval(timer);
  timer = null;
  known = null;
  owner = null;
  generation += 1;
  polling = false;
}

function explain() {
  if (!supported() || !wanted()) return "";
  if (Notification.permission === "denied") return "El navegador bloqueó las notificaciones de esta página.";
  if (Notification.permission !== "granted") return "Permite las notificaciones en el navegador para recibir avisos.";
  return "";
}

/** The top-bar toggle for `username`. Disabled where the browser cannot notify (no https and not localhost); when it
 *  is on but the browser does not allow notices, a visible note says why nothing will arrive. */
export function noticeToggle(username) {
  const box = h("input", { type: "checkbox" });
  const note = h("small", { class: "notify-note", role: "status" });
  const toggle = h("label", { class: "notify-toggle", title: "Notificación del navegador cuando una ejecución termina o falla (con la consola abierta)." },
    box, "Avisarme al terminar");
  const wrap = h("span", { class: "notify" }, toggle, note);
  if (!supported()) {
    box.disabled = true;
    toggle.title = "Este navegador no puede avisar aquí: hace falta https o localhost (por ejemplo, el túnel SSH).";
    return wrap;
  }
  const paint = () => {
    box.checked = wanted();
    note.textContent = explain();
  };
  owner = username; // the app calls startWatcher with the same user right after the shell is built
  paint();
  box.addEventListener("change", async () => {
    const wish = box.checked;
    remember(wish);
    paint(); // before the prompt: an unanswered permission request never resolves, and the note must show meanwhile
    known = null; // a fresh baseline: only jobs ending after the switch announce
    poll(); // start (or stop) watching right away
    if (wish && Notification.permission === "default") {
      await Notification.requestPermission();
      paint();
      poll();
    }
  });
  return wrap;
}
