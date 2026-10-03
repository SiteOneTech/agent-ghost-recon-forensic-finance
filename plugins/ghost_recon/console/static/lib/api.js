// JSON client for /api/v1: cookie session plus the anti-CSRF header; a 401 sends the user to the login view.
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

export function downloadUrl(path) {
  return BASE + path;
}

export async function api(path, { method = "GET", body, query } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-GR-CSRF"] = csrf;
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
