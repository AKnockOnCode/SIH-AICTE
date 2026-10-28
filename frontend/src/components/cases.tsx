// Case list table and small case-related widgets reused across screens.
import { useEffect, useState } from "react";
import type { CaseRow } from "../api/models";
import { daysLabel, fmtDate, fmtPct } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { Link, setQuery, useLocation } from "../lib/router";
import { useRefData } from "../lib/session";
import { BandChip, BureauTag, Chip, StatusChip } from "./ui";

export function SlaCell({ c }: { c: Pick<CaseRow, "status" | "overdue" | "days_remaining" | "expected_disposal_date" | "disposed_date"> }) {
  if (c.status === "DISPOSED") {
    const late = c.disposed_date && c.disposed_date > c.expected_disposal_date;
    return <span className={late ? "text-orange-ink" : "text-green-ink"}>{late ? "Disposed late" : "Disposed in time"}</span>;
  }
  if (c.overdue) return <span className="font-semibold text-red-ink">{daysLabel(c.days_remaining)}</span>;
  return (
    <span className={c.days_remaining !== null && c.days_remaining <= 3 ? "font-semibold text-orange-ink" : "text-ink"}>
      {daysLabel(c.days_remaining)}
    </span>
  );
}

export function MatchChip({ status, confidence }: { status: string; confidence: number | null }) {
  if (status === "CONFIRMED" || status === "AUTO_LINKED") return null;
  if (status === "PENDING_REVIEW") return <Chip tone="orange" title="Institution match awaits officer review">Match pending</Chip>;
  if (status === "UNMATCHED") return <Chip tone="red">Unmatched</Chip>;
  return <Chip tone="neutral" title={confidence !== null ? `Confidence ${fmtPct(confidence)}` : undefined}>{status.toLowerCase()}</Chip>;
}

export function CaseTable({ rows, showInstitution = true, compact = false }: { rows: CaseRow[]; showInstitution?: boolean; compact?: boolean }) {
  const ref = useRefData();
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Case</th>
            {showInstitution && <th scope="col">Institution</th>}
            <th scope="col">Category</th>
            <th scope="col">Bureau</th>
            <th scope="col">Status</th>
            <th scope="col">Priority</th>
            <th scope="col">Received</th>
            <th scope="col">SLA</th>
            {!compact && <th scope="col">Officer / last action</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td className="whitespace-nowrap">
                <Link to={`/cases/${c.id}`} className="font-semibold">{c.id}</Link>
                {c.source_ref && c.source_ref !== c.id && <span className="block text-xs text-muted">{c.source_ref}</span>}
                {c.master_case_id && <Link to={`/master-cases/${c.master_case_id}`} className="block text-xs">{c.master_case_id}</Link>}
              </td>
              {showInstitution && (
                <td className="min-w-48">
                  {c.institution_id ? <Link to={`/institutions/${c.institution_id}`}>{c.institution_name}</Link>
                    : <span className="text-muted">{c.institution_name_raw}</span>}
                  <span className="mt-0.5 flex flex-wrap gap-1"><MatchChip status={c.match_status} confidence={c.match_confidence} />
                    {c.demo_tag === "INSTITUTION_A" && <Chip tone="navy">Institution A</Chip>}</span>
                </td>
              )}
              <td className="min-w-40">
                <span className="block">{c.category_label ?? ref.categoryLabel(c.category_code)}</span>
                <span className="line-clamp-1 text-xs text-muted" title={c.subject}>{c.subject}</span>
              </td>
              <td><BureauTag code={c.bureau_code} name={ref.bureauName(c.bureau_code)} /></td>
              <td>
                <StatusChip status={c.status} />
                {c.escalation_level > 0 && c.status !== "ESCALATED" && <span className="block text-xs text-muted">escalated before</span>}
              </td>
              <td><BandChip band={c.effective_band} score={c.priority_score} overridden={c.effective_band !== c.priority_band} /></td>
              <td className="num whitespace-nowrap">{fmtDate(c.received_date)}</td>
              <td className="whitespace-nowrap"><SlaCell c={c} /><span className="block text-xs text-muted">due {fmtDate(c.expected_disposal_date)}</span></td>
              {!compact && (
                <td className="min-w-40 text-xs">
                  <span className="block text-ink">{c.officer_name ?? <span className="text-muted">Unassigned</span>}</span>
                  <span className="text-muted">{c.last_action_type ? ref.actionLabel(c.last_action_type) : "—"}</span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Text input bound to a URL query parameter (debounced). */
export function UrlTextInput({ param, label, placeholder, className }: { param: string; label: string; placeholder?: string; className?: string }) {
  const { params } = useLocation();
  const urlValue = params.get(param) ?? "";
  const [value, setValue] = useState(urlValue);
  const debounced = useDebounced(value, 350);
  useEffect(() => setValue(urlValue), [urlValue]);
  useEffect(() => {
    if (debounced !== urlValue) setQuery({ [param]: debounced.trim() || null, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  return (
    <label className={`flex flex-col text-xs font-semibold text-ink ${className ?? ""}`}>
      {label}
      <input className="field-input mt-1 font-normal" value={value} placeholder={placeholder} onChange={(e) => setValue(e.target.value)} />
    </label>
  );
}
