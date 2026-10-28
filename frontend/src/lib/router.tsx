// Tiny client-side router on the History API (no external dependency).
import { useSyncExternalStore, type CSSProperties, type MouseEvent, type ReactNode } from "react";

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());
if (typeof window !== "undefined") window.addEventListener("popstate", notify);

export function navigate(to: string, opts: { replace?: boolean; keepScroll?: boolean } = {}) {
  const current = window.location.pathname + window.location.search + window.location.hash;
  if (to === current) return;
  if (opts.replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  notify();
  if (!opts.keepScroll) window.scrollTo({ top: 0 });
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
const snapshot = () => window.location.pathname + window.location.search;

export interface Location {
  pathname: string;
  search: string;
  params: URLSearchParams;
}

export function useLocation(): Location {
  const href = useSyncExternalStore(subscribe, snapshot, snapshot);
  const q = href.indexOf("?");
  const pathname = q >= 0 ? href.slice(0, q) : href;
  const search = q >= 0 ? href.slice(q) : "";
  return { pathname, search, params: new URLSearchParams(search) };
}

/** Match "/cases/:id" against a path; returns params or null. */
export function matchPath(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/").filter(Boolean);
  const s = path.split("/").filter(Boolean);
  if (p.length !== s.length) return null;
  const out: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) out[p[i].slice(1)] = decodeURIComponent(s[i]);
    else if (p[i] !== s[i]) return null;
  }
  return out;
}

/** Update URL query parameters (filters live in the URL so views are shareable and survive reloads). */
export function setQuery(updates: Record<string, string | number | boolean | null | undefined | string[]>, opts: { replace?: boolean } = {}) {
  const params = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(updates)) {
    if (v === null || v === undefined || v === "" || v === false || (Array.isArray(v) && v.length === 0)) params.delete(k);
    else params.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = params.toString();
  navigate(window.location.pathname + (s ? `?${s}` : ""), { replace: opts.replace ?? true, keepScroll: true });
}

export const listParam = (params: URLSearchParams, key: string): string[] =>
  (params.get(key) ?? "").split(",").map((x) => x.trim()).filter(Boolean);

export function Link(props: { to: string; className?: string; children?: ReactNode; title?: string; "aria-label"?: string;
  "aria-current"?: "page" | undefined; onClick?: () => void; style?: CSSProperties }) {
  const { to, children, onClick, ...rest } = props;
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onClick?.();
    navigate(to);
  };
  return (
    <a href={to} onClick={handle} {...rest}>
      {children}
    </a>
  );
}
