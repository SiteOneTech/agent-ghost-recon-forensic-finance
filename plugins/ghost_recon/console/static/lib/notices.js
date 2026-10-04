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

function supported() {
  return "Notification" in window && window.isSecureContext;
}

function wanted() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false; // storage blocked: the toggle cannot be remembered, so notices stay off
  }
}

function remember(on) {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
}

function on() {
  return supported() && wanted() && Notification.permission === "granted";
}

function announce(job) {
  const notice = new Notification(`Ghost Recon · ejecución #${job.id} ${OUTCOME[job.status] || job.status}`, {
    body: `${COMMAND_LABEL[job.command] || job.command} · ${job.case_name || job.folder_name}`, tag: `gr-job-${job.id}` });
  notice.onclick = () => {
    window.focus();
    window.location.hash = `#/jobs/${job.id}`;
    notice.close();
  };
}

async function poll() {
  if (!on()) {
    known = null;
    return;
  }
  if (polling) return;
  polling = true;
  try {
    const jobs = (await api("/jobs", { query: { limit: RECENT } })).items;
    if (timer && on()) { // the watcher may have been stopped (sign-out) or switched off while the request ran
      if (known) {
        for (const job of jobs) if (!job.active && known.get(job.id) !== false) announce(job);
      }
      known = new Map(jobs.map((j) => [j.id, j.active]));
    }
  } catch {
    // signed out or the server restarting: the next poll tries again
  } finally {
    polling = false;
  }
}

export function startWatcher() {
  if (timer) return;
  timer = setInterval(poll, POLL_MS);
  poll();
}

export function stopWatcher() {
  clearInterval(timer);
  timer = null;
  known = null;
}

/** The top-bar toggle. Disabled where the browser cannot notify (no https and not localhost). */
export function noticeToggle() {
  const box = h("input", { type: "checkbox" });
  const toggle = h("label", { class: "notify-toggle", title: "Notificación del navegador cuando una ejecución termina o falla (con la consola abierta)." },
    box, "Avisarme al terminar");
  if (!supported()) {
    box.disabled = true;
    toggle.title = "Este navegador no puede avisar aquí: hace falta https o localhost (por ejemplo, el túnel SSH).";
    return toggle;
  }
  box.checked = on();
  box.addEventListener("change", async () => {
    if (box.checked && Notification.permission === "default") await Notification.requestPermission();
    box.checked = box.checked && Notification.permission === "granted";
    remember(box.checked);
    if (!box.checked && Notification.permission === "denied") {
      toggle.title = "El navegador bloqueó los avisos de esta página: permítelos en la configuración del sitio.";
    }
    known = null; // a fresh baseline: only jobs ending after the switch announce
    poll(); // start (or stop) watching right away
  });
  return toggle;
}
