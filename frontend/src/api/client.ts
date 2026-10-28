// Typed API client. Authentication is SIMULATED: the selected demo role is sent as the
// X-Demo-User header and every permission check happens on the server.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level messages from a 422 validation error, keyed by field name. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (Array.isArray(this.details)) {
      (this.details as Array<string | { loc?: unknown[]; msg?: string }>).forEach((d, i) => {
        if (typeof d === "string") {
          out[`#${i + 1}`] = d;
          return;
        }
        const loc = (d.loc ?? []).filter((x) => x !== "body");
        const key = loc.map(String).join(".") || `#${i + 1}`;
        if (!out[key]) out[key] = String(d.msg ?? "Invalid value");
      });
    }
    return out;
  }
}

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type Query = Record<string, QueryValue>;

let demoUser = "competent.authority";
export const setDemoUser = (id: string) => {
  demoUser = id;
};
export const getDemoUser = () => demoUser;

export function toQueryString(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length) p.set(k, v.join(","));
    } else {
      p.set(k, String(v));
    }
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Demo-User": demoUser, Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path + toQueryString(opts.query), { method, headers, body, signal: opts.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "The AgniDrishti server could not be reached. Check that the backend is running.");
  }
  if (!res.ok) {
    let payload: { error?: { code?: string; message?: string; details?: unknown } } | undefined;
    try {
      payload = await res.json();
    } catch {
      payload = undefined;
    }
    throw new ApiError(res.status, payload?.error?.code ?? "http_error",
      payload?.error?.message ?? `Request failed with status ${res.status}`, payload?.error?.details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get("Content-Disposition") ?? "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(cd);
  return plain ? plain[1] : fallback;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body: body ?? {}, query }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body: body ?? {} }),
  upload: <T>(path: string, form: FormData, query?: Query) => request<T>("POST", path, { form, query }),

  /** Download a file produced by the API (header-authenticated, so it goes through fetch). */
  async download(path: string, query: Query | undefined, fallbackName: string): Promise<string> {
    const res = await fetch(path + toQueryString(query), { headers: { "X-Demo-User": demoUser } });
    if (!res.ok) {
      let message = `Download failed with status ${res.status}`;
      try {
        message = (await res.json())?.error?.message ?? message;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, "download_failed", message);
    }
    const blob = await res.blob();
    const name = filenameFrom(res, fallbackName);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    return name;
  },
};
