// JSON client for /api/v1: cookie session plus the anti-CSRF header; a 401 sends the user to the login view.
// `background: true` marks a request the page makes on its own (a poll): it still needs a live session but never
// keeps one alive, so a tab nobody uses still times out.
const BASE = "/api/v1";
let csrf = null;

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function setCsrf(token) {
  csrf = token || null;
}

/** Same-origin URL of an API path, for plain links (a large ZIP downloads straight to disk this way). */
export function downloadUrl(path) {
  return BASE + path;
}

function apiUrl(path, query) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  return url;
}

async function failure(res, path) {
  let err = {};
  try {
    err = ((await res.json()) || {}).error || {};
  } catch {
    // not a JSON envelope: keep the HTTP status text
  }
  if (res.status === 401 && !path.startsWith("/auth/")) window.location.hash = "#/login";
  return new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText, null);
}

function attachmentName(header) {
  const star = /filename\*=utf-8''([^;]+)/i.exec(header || "");
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      // malformed percent-encoding: fall back to the plain filename
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header || "");
  return plain ? plain[1] : "descarga";
}

/** Download an attachment of the API without leaving the page: an error (e.g. 503 without openpyxl, 409 for a
 *  changed deliverable) comes back as ApiError instead of replacing the console with a JSON page. */
export async function download(path, query) {
  const res = await fetch(apiUrl(path, query), { credentials: "same-origin" });
  if (!res.ok) throw await failure(res, path);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = attachmentName(res.headers.get("content-disposition"));
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
}

export async function api(path, { method = "GET", body, query, background = false } = {}) {
  const url = apiUrl(path, query);
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-GR-CSRF"] = csrf;
  if (background) headers["X-GR-Background"] = "1";
  const res = await fetch(url, {
    method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body),
  });
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const err = (data && data.error) || {};
    if (res.status === 401 && !path.startsWith("/auth/")) window.location.hash = "#/login";
    throw new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText, data);
  }
  return data;
}
