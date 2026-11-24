import { API_V1 } from "./config";
import { forgetInFlight, shareGet, type Shared } from "./inflight";
// Thin fetch wrapper. Same-origin (/api is proxied to FastAPI), HTTP-only session cookie, CSRF header from the
// readable csrf cookie. Google/AI secrets never reach the browser.
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : messageFrom(detail));
    this.status = status;
    this.detail = detail;
  }
  get code(): string | undefined {
    const d = this.detail as { code?: string } | undefined;
    return d && typeof d === "object" ? d.code : undefined;
  }
}

function messageFrom(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const loc = Array.isArray(e?.loc) ? e.loc.filter((x: unknown) => x !== "body").join(".") : "";
        return `${loc ? loc + ": " : ""}${String(e?.msg ?? "Invalid value").replace(/^Value error, /, "")}`;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return "Something went wrong. Please try again.";
}

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie.split("; ").find((c) => c.startsWith("flowqr_csrf="))?.split("=")[1];
}

type Opts = { method?: string; body?: unknown; raw?: Blob; headers?: Record<string, string>; params?: Record<string, string | number | undefined | null>; signal?: AbortSignal; keepalive?: boolean };

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const qs = opts.params
    ? "?" + new URLSearchParams(Object.entries(opts.params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString()
    : "";
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.raw) headers["Content-Type"] = opts.raw.type || "application/octet-stream";
  else if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const t = csrfToken();
    if (t) headers["X-CSRF-Token"] = t;
  }
  const url = `${API_V1}${path}${qs === "?" ? "" : qs}`;
  const init: RequestInit = { method, headers, credentials: "include", signal: opts.signal, keepalive: opts.keepalive, body: opts.raw ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined) };
  const send = async (): Promise<Shared> => {
    try { const r = await fetch(url, init); return { status: r.status, text: r.status === 204 ? "" : await r.text(), failed: false }; }
    catch { return { status: 0, text: "", failed: true }; }
  };
  // Identical GETs made at the same moment share one request (lib/inflight.ts). Writes drop whatever is in flight before and after, so a refetch is always fresh.
  const shared = method === "GET" && !opts.signal && !opts.keepalive;
  if (method !== "GET") forgetInFlight();
  const got = shared ? await shareGet(url + (opts.headers ? "|" + JSON.stringify(opts.headers) : ""), send) : await send(); // the key carries any caller-set headers, so a request scoped by header is never joined with another's
  if (method !== "GET") forgetInFlight();
  if (got.failed) throw new ApiError(0, "Can't reach FlowQR right now. Check your connection and try again.");
  if (got.status === 204) return undefined as T;
  const text = got.text;
  let data: unknown = undefined;
  try { data = text ? JSON.parse(text) : undefined; } catch { /* non-JSON */ }
  if (got.status < 200 || got.status >= 300) {
    const detail = (data as { detail?: unknown } | undefined)?.detail ?? "Something went wrong. Please try again.";
    throw new ApiError(got.status, detail);
  }
  return data as T;
}

export const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

/** For endpoints that answer with a file (QR previews, bulk ZIPs). Failures are still JSON and become the same ApiError as api(). */
export async function apiFile(path: string, opts: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<{ blob: Blob; headers: Headers }> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") { const t = csrfToken(); if (t) headers["X-CSRF-Token"] = t; }
  let res: Response;
  try {
    res = await fetch(`${API_V1}${path}`, { method, headers, credentials: "include", signal: opts.signal, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach FlowQR right now. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail: unknown = "Something went wrong. Please try again.";
    try { detail = ((await res.json()) as { detail?: unknown }).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return { blob: await res.blob(), headers: res.headers };
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
