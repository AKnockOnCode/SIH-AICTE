// URL-backed filter bar shared by the dashboard, reports and search screens.
import type { ReactNode } from "react";
import { LuRotateCcw } from "react-icons/lu";
import type { Query } from "../api/client";
import { listParam, setQuery, useLocation } from "../lib/router";
import { useRefData } from "../lib/session";
import { Button, MultiSelect } from "./ui";

export type FilterKey = "dates" | "bureau" | "region" | "state" | "category" | "status" | "priority";
const LIST_KEYS = ["bureau", "region", "state", "category", "status", "priority"] as const;

/** Read the standard filters from the URL into an API query object. */
export function urlFilters(params: URLSearchParams, show: FilterKey[]): Query {
  const q: Query = {};
  if (show.includes("dates")) {
    q.date_from = params.get("date_from") || undefined;
    q.date_to = params.get("date_to") || undefined;
  }
  for (const k of LIST_KEYS) if (show.includes(k)) q[k] = listParam(params, k);
  return q;
}

/** Build a URL query string carrying the given filters (for links into the case search). */
export function filterLink(base: string, q: Query): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    p.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = p.toString();
  return s ? `${base}?${s}` : base;
}

const STATUSES = ["RECEIVED", "PENDING", "UNDER_PROCESS", "TRANSFERRED", "ESCALATED", "DISPOSED"];
const BANDS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function FilterBar({ show, children, resetKeys = [] }: { show: FilterKey[]; children?: ReactNode; resetKeys?: string[] }) {
  const { params } = useLocation();
  const ref = useRefData();
  const has = (k: FilterKey) => show.includes(k);
  const active = [...(has("dates") ? ["date_from", "date_to"] : []), ...LIST_KEYS.filter((k) => has(k)), ...resetKeys]
    .some((k) => params.get(k));
  const clear = () => {
    const u: Record<string, null> = { page: null };
    for (const k of ["date_from", "date_to", ...LIST_KEYS, ...resetKeys]) u[k] = null;
    setQuery(u);
  };
  const multi = (key: (typeof LIST_KEYS)[number], label: string, options: Array<{ value: string; label: string }>) => (
    <MultiSelect key={key} label={label} options={options} value={listParam(params, key)} className="w-full sm:w-52"
      onChange={(v) => setQuery({ [key]: v, page: null })} />
  );
  return (
    <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3 print:hidden" aria-label="Filters">
      {has("dates") && (
        <>
          <label className="flex w-full flex-col text-xs font-semibold text-ink sm:w-40">
            Received from
            <input type="date" className="field-input mt-1 font-normal" value={params.get("date_from") ?? ""}
              onChange={(e) => setQuery({ date_from: e.target.value, page: null })} />
          </label>
          <label className="flex w-full flex-col text-xs font-semibold text-ink sm:w-40">
            Received to
            <input type="date" className="field-input mt-1 font-normal" value={params.get("date_to") ?? ""}
              onChange={(e) => setQuery({ date_to: e.target.value, page: null })} />
          </label>
        </>
      )}
      {has("bureau") && multi("bureau", "Bureau/Cell", ref.bureaus.map((b) => ({ value: b.code, label: `${b.code}, ${b.name}` })))}
      {has("region") && multi("region", "Region", ref.regions.map((r) => ({ value: r.code, label: r.name })))}
      {has("state") && multi("state", "State", ref.states.map((s) => ({ value: s.name, label: s.name })))}
      {has("category") && multi("category", "Category", ref.categories.map((c) => ({ value: c.code, label: c.label })))}
      {has("status") && multi("status", "Status", STATUSES.map((s) => ({ value: s, label: ref.statusLabel(s) })))}
      {has("priority") && multi("priority", "Priority", BANDS.map((b) => ({ value: b, label: b.charAt(0) + b.slice(1).toLowerCase() })))}
      {children}
      <Button variant="ghost" size="sm" icon={<LuRotateCcw aria-hidden />} onClick={clear} disabled={!active} className="mb-1">
        Clear filters
      </Button>
    </div>
  );
}
