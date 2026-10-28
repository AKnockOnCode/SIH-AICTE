import { useState } from "react";
import { LuBellRing, LuCheck, LuCircleAlert, LuGitCompareArrows, LuHourglass, LuInfo, LuRefreshCw, LuRotateCcw, LuShieldAlert, LuUserCheck, LuX } from "react-icons/lu";
import { api } from "../api/client";
import type { AlertPage, AlertRow, SweepOut } from "../api/models";
import { UrlTextInput } from "../components/cases";
import { useTitle } from "../components/layout";
import { Button, Card, Chip, Empty, ErrorState, Field, InlineError, Loading, Modal, MultiSelect, PageHeader, Pagination, type Tone } from "../components/ui";
import { fmtDateTime, fmtNum, humanize, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";

const TYPES: Record<string, string> = {
  OVERLAP: "Overlap / conflict", SLA_OVERDUE: "Overdue (beyond SLA)", SLA_WARNING: "Due soon", PREDICTED_BREACH: "Predicted SLA breach",
  PENDING_REMINDER: "Pending reminder (no recent action)", ESCALATION: "Escalation", MATCH_REVIEW: "Institution match review", AUDIT_WARNING: "Audit / security warning",
};
const SEV_TONE: Record<string, Tone> = { CRITICAL: "red", WARNING: "orange", INFO: "blue" };
const STATE_TONE: Record<string, Tone> = { NEW: "orange", ACKNOWLEDGED: "blue", RESOLVED: "green", DISMISSED: "neutral" };

function TypeIcon({ type, severity }: { type: string; severity: string }) {
  const cls = `mt-0.5 shrink-0 text-lg ${severity === "CRITICAL" ? "text-red-ink" : severity === "WARNING" ? "text-orange-ink" : "text-blue-ink"}`;
  if (type === "OVERLAP") return <LuGitCompareArrows aria-hidden className={cls} />;
  if (type === "MATCH_REVIEW") return <LuUserCheck aria-hidden className={cls} />;
  if (type === "AUDIT_WARNING") return <LuShieldAlert aria-hidden className={cls} />;
  if (type === "PREDICTED_BREACH" || type === "SLA_WARNING") return <LuHourglass aria-hidden className={cls} />;
  if (type === "PENDING_REMINDER") return <LuBellRing aria-hidden className={cls} />;
  if (type === "ESCALATION" || type === "SLA_OVERDUE") return <LuCircleAlert aria-hidden className={cls} />;
  return <LuInfo aria-hidden className={cls} />;
}

export function AlertsPage() {
  useTitle("Alerts Center");
  const { params } = useLocation();
  const { can } = useSession();
  const page = Number(params.get("page") ?? "1") || 1;
  const states = listParam(params, "state");
  const query = {
    alert_type: listParam(params, "type"), severity: listParam(params, "severity"), state: states.length ? states : ["NEW", "ACKNOWLEDGED"],
    q: params.get("q") || undefined, date_from: params.get("date_from") || undefined, date_to: params.get("date_to") || undefined,
    case_id: params.get("case_id") || undefined, institution_id: params.get("institution_id") || undefined, page, page_size: 25,
  };
  const { data, error, loading, reload } = useApi<AlertPage>("/api/alerts", query);
  const [acting, setActing] = useState<{ alert: AlertRow; action: "RESOLVE" | "DISMISS" } | null>(null);
  const toast = useToast();
  const { bump } = useSession();
  const quick = async (a: AlertRow, action: "ACKNOWLEDGE" | "REOPEN") => {
    try {
      await api.post(`/api/alerts/${a.id}/act`, { action });
      toast.push(`${a.id} ${action === "ACKNOWLEDGE" ? "acknowledged" : "re-opened"}.`);
      bump();
    } catch (e) {
      toast.push((e as Error).message, "error");
    }
  };
  const totals = data ? Object.entries(data.counts).map(([t, by]) => [t, Object.entries(by).filter(([s]) => s === "NEW").reduce((x, [, n]) => x + n, 0)] as const) : [];
  return (
    <div>
      <PageHeader title="Alerts centre"
        subtitle="Overlap and conflict alerts, SLA warnings, overdue notices, predicted breaches, pending reminders, escalations, match reviews and audit warnings for your role."
        meta={data && <Chip tone="neutral">{data.delivery_note}</Chip>}
        actions={can("system.sweep") && <Button size="sm" icon={<LuRefreshCw aria-hidden />} onClick={async () => {
          try {
            const r = await api.post<SweepOut>("/api/alerts/sweep");
            toast.push(`Alerts refreshed: ${r.overdue} overdue, ${r.due_soon} due soon, ${r.predicted} predicted breaches, ${r.reminders} reminders, ${r.auto_resolved} closed automatically.`, "info");
            bump();
          } catch (e) {
            toast.push((e as Error).message, "error");
          }
        }}>Refresh time-based alerts</Button>} />
      {data && (
        <div className="mb-3 flex flex-wrap gap-2">
          {totals.map(([t, n]) => (
            <button key={t} type="button" onClick={() => setQuery({ type: t, state: "NEW", page: null })}
              className="rounded-md border border-line bg-white px-3 py-1.5 text-left text-xs hover:border-blue/50">
              <span className="num block text-base font-bold text-navy-ink">{fmtNum(n)}</span>
              <span className="text-muted">{TYPES[t] ?? humanize(t)}, new</span>
            </button>
          ))}
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
        <MultiSelect label="Type" className="w-full sm:w-56" value={listParam(params, "type")} onChange={(v) => setQuery({ type: v, page: null })}
          options={Object.entries(TYPES).map(([value, label]) => ({ value, label }))} />
        <MultiSelect label="Severity" className="w-full sm:w-44" value={listParam(params, "severity")} onChange={(v) => setQuery({ severity: v, page: null })}
          options={["CRITICAL", "WARNING", "INFO"].map((s) => ({ value: s, label: humanize(s) }))} />
        <MultiSelect label="State" className="w-full sm:w-52" value={states} onChange={(v) => setQuery({ state: v, page: null })}
          options={["NEW", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"].map((s) => ({ value: s, label: humanize(s) }))} />
        <label className="flex flex-col text-xs font-semibold text-ink">From
          <input type="date" className="field-input mt-1 w-40 font-normal" value={params.get("date_from") ?? ""} onChange={(e) => setQuery({ date_from: e.target.value, page: null })} /></label>
        <label className="flex flex-col text-xs font-semibold text-ink">To
          <input type="date" className="field-input mt-1 w-40 font-normal" value={params.get("date_to") ?? ""} onChange={(e) => setQuery({ date_to: e.target.value, page: null })} /></label>
        <UrlTextInput param="q" label="Search" placeholder="Title, case or institution" className="w-full sm:w-60" />
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && data.total === 0 && <Empty title="No alerts match these filters">Unacknowledged alerts are shown by default; widen the state filter to see closed ones.</Empty>}
      {data && data.total > 0 && (
        <Card title={`${fmtNum(data.total)} alert${data.total === 1 ? "" : "s"}`} subtitle={`${fmtNum(data.unread)} new (unacknowledged) for your role`}>
          <ul className="divide-y divide-line">
            {data.items.map((a) => (
              <li key={a.id} className={`flex gap-3 py-3 ${a.state === "NEW" ? "" : "opacity-80"}`}>
                <TypeIcon type={a.alert_type} severity={a.severity} />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className={`font-semibold ${a.state === "NEW" ? "text-ink" : "text-muted"}`}>{a.title}</span>
                    <Chip tone={SEV_TONE[a.severity] ?? "neutral"}>{humanize(a.severity)}</Chip>
                    <Chip tone={STATE_TONE[a.state] ?? "neutral"}>{humanize(a.state)}</Chip>
                  </p>
                  <p className="mt-0.5 text-sm text-ink">{a.message}</p>
                  <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                    <span>{TYPES[a.alert_type] ?? a.alert_type}</span>
                    <span>{fmtDateTime(a.created_at)}</span>
                    {a.case_id && <Link to={`/cases/${a.case_id}`}>{a.case_id}</Link>}
                    {a.institution_id && <Link to={`/institutions/${a.institution_id}`}>{a.institution_name ?? a.institution_id}</Link>}
                    {a.overlap_alert_id && <Link to={`/overlaps/${a.overlap_alert_id}`}>{a.overlap_alert_id}</Link>}
                    {a.target_bureau && <span>For {a.target_bureau}</span>}
                    {a.target_region && <span>Region {humanize(a.target_region)}</span>}
                    <span>{a.id}, {humanize(a.channel)}</span>
                  </p>
                  {a.acted_by && <p className="mt-1 text-xs text-ink">{humanize(a.state)} by {a.acted_by} ({roleLabel(a.acted_role)}), {fmtDateTime(a.acted_at)}{a.action_remarks ? `: ${a.action_remarks}` : ""}</p>}
                </div>
                {can("alert.act") && (
                  <div className="flex shrink-0 flex-col gap-1">
                    {a.state === "NEW" && <Button size="sm" icon={<LuCheck aria-hidden />} onClick={() => quick(a, "ACKNOWLEDGE")}>Acknowledge</Button>}
                    {(a.state === "NEW" || a.state === "ACKNOWLEDGED") && <>
                      <Button size="sm" onClick={() => setActing({ alert: a, action: "RESOLVE" })}>Resolve</Button>
                      <Button size="sm" variant="ghost" icon={<LuX aria-hidden />} onClick={() => setActing({ alert: a, action: "DISMISS" })}>Dismiss</Button>
                    </>}
                    {(a.state === "RESOLVED" || a.state === "DISMISSED") && <Button size="sm" variant="ghost" icon={<LuRotateCcw aria-hidden />} onClick={() => quick(a, "REOPEN")}>Re-open</Button>}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <Pagination page={page} pageSize={25} total={data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />
        </Card>
      )}
      <ActDialog acting={acting} onClose={() => setActing(null)} />
    </div>
  );
}

function ActDialog({ acting, onClose }: { acting: { alert: AlertRow; action: "RESOLVE" | "DISMISS" } | null; onClose: () => void }) {
  const [remarks, setRemarks] = useState("");
  const { busy, error, run } = useAction();
  const toast = useToast();
  const { bump } = useSession();
  if (!acting) return null;
  const verb = acting.action === "RESOLVE" ? "Resolve" : "Dismiss";
  return (
    <Modal open title={`${verb} ${acting.alert.id}`} onClose={onClose} description={acting.alert.title}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={remarks.trim().length < 3} onClick={async () => {
          const out = await run(() => api.post(`/api/alerts/${acting.alert.id}/act`, { action: acting.action, remarks }));
          if (out !== undefined) {
            toast.push(`${acting.alert.id} ${acting.action === "RESOLVE" ? "resolved" : "dismissed"}.`);
            bump();
            setRemarks("");
            onClose();
          }
        }}>{verb}</Button>
      </>}>
      <Field label="Remarks" required hint="Mandatory: saved with the alert and in the audit trail.">
        {(id) => <textarea id={id} rows={3} className="field-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />}
      </Field>
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}
