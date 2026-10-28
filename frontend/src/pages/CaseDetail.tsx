import { useState, type ReactNode } from "react";
import {
  LuArrowRightLeft, LuArrowUp, LuCircleCheck, LuDownload, LuFilePlus, LuFileText, LuGitCompareArrows, LuLink, LuMessageSquareText,
  LuRotateCcw, LuSlidersHorizontal, LuTriangleAlert, LuUserCheck,
} from "react-icons/lu";
import { api } from "../api/client";
import type { ActionResult, CaseDetail, Chip as PriorityChip, OverlapRef, TimelineEntry } from "../api/models";
import { SlaBar } from "../components/charts";
import { useTitle } from "../components/layout";
import {
  BandChip, BureauTag, Button, Card, Chip, Empty, ErrorState, Field, InlineError, KeyValues, Loading, Modal, PageHeader, SelectInput,
  StatusChip, SyntheticBadge, TierChip,
} from "../components/ui";
import { fmtDate, fmtDateTime, fmtNum, fmtPct, humanize, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

const TRANSITIONS: Record<string, string[]> = {
  RECEIVED: ["PENDING", "UNDER_PROCESS"], PENDING: ["UNDER_PROCESS"], UNDER_PROCESS: ["PENDING"],
  TRANSFERRED: ["PENDING", "UNDER_PROCESS"], ESCALATED: ["UNDER_PROCESS"], DISPOSED: [],
};
const DOC_TYPES = ["EVIDENCE", "LETTER", "NOTICE", "REPLY", "REPORT", "ORDER", "OTHER"];

type Op = "action" | "status" | "assign" | "transfer" | "escalate" | "deescalate" | "dispose" | "reopen" | "override" | "document";

export function CaseDetailPage({ id }: { id: string }) {
  useTitle("Case Workflow", id);
  const { data, error, loading, reload } = useApi<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`);
  const [op, setOp] = useState<Op | null>(null);
  const [raised, setRaised] = useState<OverlapRef[]>([]);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  const c = data.case;
  return (
    <div>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">{c.id}<StatusChip status={c.status} />
          <BandChip band={c.effective_band} score={c.priority_score} overridden={data.priority.overridden} /></span>}
        subtitle={c.subject}
        meta={<>
          {c.is_synthetic ? <SyntheticBadge label="Synthetic case" /> : <Chip tone="blue">Entered / imported record</Chip>}
          {c.demo_tag === "INSTITUTION_A" && <Chip tone="navy">Institution A demo story</Chip>}
          {c.master_case_id && <Link to={`/master-cases/${c.master_case_id}`}><Chip tone="blue">Master Case {c.master_case_id}</Chip></Link>}
          {c.escalation_level > 0 && <Chip tone="navy">Escalation level {c.escalation_level}</Chip>}
        </>}
        actions={<>
          {c.institution_id && <Button variant="secondary" onClick={() => window.open(`/institutions/${c.institution_id}/dossier`, "_blank")}
            icon={<LuFileText aria-hidden />}>Institution dossier</Button>}
          <Link to={`/audit?entity_id=${c.id}`} className="text-sm font-semibold">Audit trail</Link>
        </>} />

      {raised.length > 0 && <RaisedAlerts alerts={raised} onClose={() => setRaised([])} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-8">
          <Facts data={data} />
          <PriorityCard data={data} />
          <Card title="Action timeline" subtitle="Every recorded step, oldest first. Remarks and actors are kept permanently (audited).">
            <Timeline entries={data.timeline} next={c.status !== "DISPOSED" ? { label: c.next_action, due: c.next_action_due } : null} />
          </Card>
          <Card title="Complaint text"><p className="text-sm whitespace-pre-wrap text-ink">{data.description}</p></Card>
          <Documents data={data} onAdd={() => setOp("document")} />
        </div>
        <div className="space-y-4 xl:col-span-4">
          <ActionsPanel data={data} onOp={setOp} />
          <SlaCard data={data} />
          <BreachCard data={data} />
          <OverlapsCard data={data} reload={reload} />
          <Card title="Complainant and references" subtitle="Identity is not stored in this prototype (data minimisation)">
            <KeyValues cols={1} items={[
              ["Complainants", `${fmtNum(Number(data.complainant.count ?? 1))} (${humanize(String(data.complainant.type ?? "STUDENT"))})`],
              ["Evidence", String(data.complainant.evidence_note ?? `${data.complainant.evidence_count ?? 0} item(s)`)],
              ["Court / VIP / Parliament reference", data.complainant.reference_flag === "NONE" ? "None"
                : `${humanize(String(data.complainant.reference_flag))}${data.complainant.reference_note ? `: ${data.complainant.reference_note}` : ""}`],
            ]} />
          </Card>
        </div>
      </div>
      <OperationDialog op={op} data={data} onClose={() => setOp(null)} onDone={(result) => {
        setOp(null);
        reload();
        const alerts = (result as { overlap_alerts?: OverlapRef[] } | undefined)?.overlap_alerts;
        if (alerts && alerts.length) setRaised(alerts);
      }} />
    </div>
  );
}

function RaisedAlerts({ alerts, onClose }: { alerts: OverlapRef[]; onClose: () => void }) {
  const conflict = alerts.some((a) => a.tier === "CONFLICT");
  return (
    <div className={`mb-4 rounded-lg border-2 px-4 py-3 ${conflict ? "border-red bg-red-soft" : "border-orange bg-orange-soft"}`} role="alert">
      <p className={`flex items-center gap-2 text-base font-bold ${conflict ? "text-red-ink" : "text-orange-ink"}`}>
        <LuTriangleAlert aria-hidden />
        {conflict ? "Potential Overlapping Cases – Coordination Required" : "Overlap detected"}
      </p>
      <p className="mt-1 text-sm text-ink">This action was checked against open cases at the same institution in every Bureau/Cell:</p>
      <ul className="mt-1 space-y-1 text-sm">
        {alerts.map((a) => (
          <li key={a.alert_id} className="flex flex-wrap items-center gap-2">
            <TierChip tier={a.tier} />
            <Link to={`/overlaps/${a.alert_id}`} className="font-semibold">{a.alert_id}</Link>
            <span className="text-muted">{a.created ? "new alert" : "existing alert updated"}: {a.cases.join(", ")}</span>
          </li>
        ))}
      </ul>
      <Button size="sm" variant="ghost" onClick={onClose} className="mt-1">Dismiss this notice</Button>
    </div>
  );
}

function Facts({ data }: { data: CaseDetail }) {
  const c = data.case;
  const ref = useRefData();
  const inst = data.institution as { id: string; name: string; permanent_id: string | null; district: string | null; state: string } | null;
  return (
    <Card title="Case facts">
      <KeyValues cols={3} items={[
        ["Case ID (AgniDrishti)", <span className="font-semibold">{c.id}</span>],
        ["Source ID", c.source_ref ?? "—"],
        ["External reference", c.external_ref ?? "—"],
        ["Institution", inst ? <span><Link to={`/institutions/${inst.id}`} className="font-semibold">{inst.name}</Link>
          <span className="block text-xs text-muted">{inst.permanent_id ?? "No Permanent ID"}, {inst.district ? `${inst.district}, ` : ""}{inst.state}</span></span>
          : <span className="text-orange-ink">Not linked yet</span>],
        ["Name as received", <span>{c.institution_name_raw}<span className="block text-xs text-muted">Match: {humanize(c.match_status)}
          {c.match_confidence !== null ? `, confidence ${fmtPct(c.match_confidence)}` : ""}</span></span>],
        ["Category", <span>{c.category_label}<span className="block text-xs text-muted">Severity {String(data.rule.severity_level)}/5, SLA {String(data.rule.sla_days)} days</span></span>],
        ["Bureau/Cell", <span className="flex items-center gap-2"><BureauTag code={c.bureau_code} /> {ref.bureauName(c.bureau_code)}</span>],
        ["Assigned officer", c.officer_name ?? <span className="text-orange-ink">Unassigned</span>],
        ["Received", fmtDate(c.received_date)],
        ["Due (SLA)", <span>{fmtDate(c.expected_disposal_date)}{c.status === "DISPOSED" && c.disposed_date ? `, disposed ${fmtDate(c.disposed_date)}` : ""}</span>],
        ["Last action", c.last_action_type ? `${ref.actionLabel(c.last_action_type)}, ${fmtDateTime(c.last_action_at)}` : "—"],
        ["Next action", c.status === "DISPOSED" ? `Disposed: ${humanize(c.outcome)}` : c.next_action ? `${c.next_action}${c.next_action_due ? ` (due ${fmtDate(c.next_action_due)})` : ""}` : "—"],
        ["Region / State", `${ref.regionName(c.region_code)}, ${c.state ?? "—"}`],
        ["Transfers", fmtNum(c.transfer_count)],
        ["Match review", data.match_review ? <Link to="/match-reviews">Pending review {String(data.match_review.id ?? "")}</Link> : "Not needed"],
      ]} />
    </Card>
  );
}

function PriorityCard({ data }: { data: CaseDetail }) {
  const p = data.priority;
  return (
    <Card title={<span className="flex items-center gap-2">Priority: why this band <BandChip band={p.effective_band} score={p.score} overridden={p.overridden} /></span>}
      subtitle="Transparent rule-based score; each chip shows its contribution. The text model is advisory only.">
      <ul className="flex flex-wrap gap-2">
        {p.chips.map((ch: PriorityChip) => (
          <li key={ch.key} title={ch.detail ?? undefined}
            className={`rounded-md border px-2.5 py-1.5 text-xs ${ch.kind === "ml" ? "border-dashed border-line-strong bg-white"
              : ch.kind === "keyword" ? "border-red/40 bg-red-soft" : ch.points > 0 ? "border-blue/30 bg-blue-soft" : "border-line bg-slate-soft"}`}>
            <span className="font-semibold text-ink">{ch.label}</span>
            {ch.kind !== "ml" && <span className="num ml-1.5 text-muted">{ch.points > 0 ? `+${ch.points.toFixed(1)}` : ch.points.toFixed(1)}</span>}
            {ch.detail && <span className="mt-0.5 block text-muted">{ch.detail}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-3 rounded-md bg-tint px-3 py-2 font-mono text-xs text-ink">{p.formula}</p>
      {data.priority_overrides.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-ink">Override history</p>
          <ul className="mt-1 space-y-1 text-xs text-muted">
            {data.priority_overrides.map((o, i) => (
              <li key={i}>{fmtDateTime(String(o.created_at))}: {String(o.previous_band ?? "—")} → {String(o.new_band ?? "computed band")} by {String(o.actor_id)}
                {o.bureau_code ? ` (${String(o.bureau_code)})` : ""}. Reason: {String(o.reason)}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function Timeline({ entries, next }: { entries: TimelineEntry[]; next: { label: string | null; due: string | null } | null }) {
  const ref = useRefData();
  const officer = new Map(ref.officers.map((o) => [o.id, o.display_name]));
  const who = (x: string | null) => (x ? officer.get(x) ?? x : "");
  if (!entries.length) return <Empty title="No actions recorded yet" />;
  return (
    <ol className="relative ml-2 border-l-2 border-line pl-6">
      {entries.map((t, i) => {
        const current = i === entries.length - 1 && next !== null;
        return (
          <li key={t.id} className="relative pb-5 last:pb-2">
            <span aria-hidden className={`absolute top-1 -left-[33px] h-4 w-4 rounded-full border-2 border-white ${current ? "bg-orange" : "bg-green"}`} />
            <p className="text-sm font-semibold text-ink">{ref.actionLabel(t.action_type)}
              {t.from_value || t.to_value ? <span className="font-normal text-muted"> {who(t.from_value)}{t.from_value ? " → " : "→ "}{who(t.to_value)}</span> : null}</p>
            <p className="text-xs text-muted">{fmtDateTime(t.action_at)}, {who(t.actor_label)}{t.actor_role ? ` (${roleLabel(t.actor_role)})` : ""}
              {t.bureau_code ? `, ${t.bureau_code}` : ""}{t.is_synthetic ? ", synthetic history" : ""}</p>
            {t.remarks && <p className="mt-1 text-sm text-ink">{t.remarks}</p>}
            {t.next_action && <p className="mt-0.5 text-xs text-muted">Next: {t.next_action}{t.next_action_due ? ` by ${fmtDate(t.next_action_due)}` : ""}</p>}
          </li>
        );
      })}
      {next && next.label && (
        <li className="relative pb-1">
          <span aria-hidden className="absolute top-1 -left-[33px] h-4 w-4 rounded-full border-2 border-white bg-slate" />
          <p className="text-sm font-semibold text-muted">{next.label}</p>
          <p className="text-xs text-muted">{next.due ? `due ${fmtDate(next.due)}` : "not scheduled"}</p>
        </li>
      )}
    </ol>
  );
}

function SlaCard({ data }: { data: CaseDetail }) {
  const s = data.sla;
  return (
    <Card title="SLA" tone="tint" subtitle={`${s.sla_days}-day SLA for ${data.case.category_label ?? "this category"} (configurable in Priority rules)`}>
      {s.is_open ? <SlaBar pct={s.pct_used} state={s.state} label={s.label} /> : <p className="text-sm text-ink">{s.label}</p>}
      <div className="mt-3"><KeyValues items={[["Due date", fmtDate(s.due_date)], ["Age", `${s.age_days} days`]]} /></div>
      {s.overdue && <p className="mt-2 text-sm font-semibold text-red-ink">Overdue by {s.overdue_by_days} day(s). This is a fact, not a prediction.</p>}
    </Card>
  );
}

function BreachCard({ data }: { data: CaseDetail }) {
  const b = data.breach;
  if (!b.applicable) {
    return <Card title="SLA breach forecast"><p className="text-sm text-muted">{b.reason ?? "Not applicable to this case."}</p></Card>;
  }
  if (b.is_fact) {
    return <Card title="SLA breach forecast"><p className="text-sm text-ink">{b.reason ?? "The due date has passed: the case is overdue."}</p></Card>;
  }
  const high = b.band === "HIGH";
  const model = b.model as { method?: string; c_index?: number; n_cases?: number } | null;
  return (
    <Card title={high ? "Forecast: may breach SLA" : "SLA breach forecast"} tone={high ? "alert" : "default"}
      subtitle="Model estimate from synthetic case history: a prompt for attention, not a fact">
      <p className={`num text-3xl font-bold ${high ? "text-red-ink" : b.band === "MEDIUM" ? "text-orange-ink" : "text-green-ink"}`}>
        {fmtPct(b.probability)} <span className="text-sm font-semibold">chance of missing the due date</span>
      </p>
      <p className="mt-1 text-xs text-muted">Band {humanize(b.band)} (alert threshold {fmtPct(b.threshold)}). Due in {b.due_in_days} day(s).</p>
      {high && <p className="mt-2 text-sm text-ink">An in-app reminder has been raised for the assigned officer and Bureau/Cell.</p>}
      <p className="mt-3 text-xs font-semibold text-ink">What drives this estimate</p>
      <ul className="mt-1 space-y-1 text-xs">
        {b.factors.map((f) => (
          <li key={f.factor} className="flex justify-between gap-3">
            <span className="text-ink">{f.label}</span>
            <span className={f.direction === "+" ? "text-red-ink" : "text-green-ink"} title={`Disposal hazard ratio ${f.hazard_ratio}`}>{f.effect}</span>
          </li>
        ))}
      </ul>
      {b.historical_reference && <p className="mt-2 text-xs text-muted">{String(b.historical_reference.text ?? "")}</p>}
      {model && <p className="mt-2 text-xs text-muted">{model.method}. Concordance (C-index) {model.c_index} on {fmtNum(model.n_cases ?? 0)} synthetic cases.</p>}
    </Card>
  );
}

function OverlapsCard({ data, reload }: { data: CaseDetail; reload: () => void }) {
  const { can } = useSession();
  const [removing, setRemoving] = useState<string | null>(null);
  const master = data.master_case as { id: string; kind: string; title: string; status: string } | null;
  const active = data.links.filter((l) => l.active);
  return (
    <Card title="Overlaps, links and Master Case">
      {data.overlap_alerts.length === 0 && active.length === 0 && !master && <p className="text-sm text-muted">No overlap alert or link involves this case.</p>}
      {data.overlap_alerts.length > 0 && (
        <ul className="space-y-2">
          {data.overlap_alerts.map((o) => (
            <li key={o.id}>
              <Link to={`/overlaps/${o.id}`} className="flex items-start gap-2 no-underline">
                <LuGitCompareArrows aria-hidden className={`mt-0.5 shrink-0 ${o.tier === "CONFLICT" ? "text-red" : "text-orange"}`} />
                <span className="text-sm">
                  <span className={`block font-semibold ${o.tier === "CONFLICT" ? "text-red-ink" : "text-ink"}`}>{o.headline}</span>
                  <span className="text-xs text-muted">{o.id}, {humanize(o.tier)}, {humanize(o.status)}{o.recommended_lead ? `, suggested lead ${o.recommended_lead}` : ""}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {active.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-ink">Linked cases</p>
          <ul className="mt-1 space-y-1 text-sm">
            {active.map((l) => {
              const other = l.case_a === data.case.id ? l.case_b : l.case_a;
              return (
                <li key={l.id} className="flex flex-wrap items-center gap-2">
                  <LuLink aria-hidden className="text-muted" />
                  <Link to={`/cases/${other}`}>{other}</Link>
                  <Chip tone="neutral">{humanize(l.link_type)}</Chip>
                  {can("overlap.act") && <button type="button" className="text-xs text-red-ink hover:underline" onClick={() => setRemoving(l.id)}>Remove link</button>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {master && (
        <p className="mt-3 text-sm">Member of <Link to={`/master-cases/${master.id}`} className="font-semibold">{master.id}</Link>: {master.title}
          <span className="block text-xs text-muted">{humanize(master.kind)}, {humanize(master.status)}. The case keeps its own ID and history.</span></p>
      )}
      <RemarksDialog open={!!removing} title="Remove case link" confirmLabel="Remove link" onClose={() => setRemoving(null)}
        description="The link is deactivated, not deleted: it stays in the case history and the audit trail."
        submit={(remarks) => api.post(`/api/links/${removing}/remove`, { remarks })} onDone={() => {
          setRemoving(null);
          reload();
        }} />
    </Card>
  );
}

function Documents({ data, onAdd }: { data: CaseDetail; onAdd: () => void }) {
  const toast = useToast();
  return (
    <Card title="Documents and evidence references" actions={data.allowed_ops.includes("document") &&
      <Button size="sm" icon={<LuFilePlus aria-hidden />} onClick={onAdd}>Add reference or file</Button>}>
      {data.documents.length === 0 ? <p className="text-sm text-muted">No document references.</p> : (
        <ul className="divide-y divide-line">
          {data.documents.map((d) => (
            <li key={d.id} className="flex flex-wrap items-start justify-between gap-2 py-2 text-sm">
              <span>
                <span className="font-semibold text-ink">{d.title}</span>
                <span className="block text-xs text-muted">{humanize(d.doc_type)}{d.reference_no ? `, ref ${d.reference_no}` : ""}, added {fmtDateTime(d.created_at)}
                  {d.added_by ? ` by ${d.added_by}` : ""}{d.is_synthetic ? " (synthetic metadata, no file)" : ""}</span>
                {d.sha256 && <span className="block font-mono text-[11px] text-muted">SHA-256 {d.sha256.slice(0, 16)}…</span>}
              </span>
              {d.downloadable && (
                <Button size="sm" icon={<LuDownload aria-hidden />} onClick={() => {
                  api.download(`/api/documents/${d.id}/download`, undefined, d.file_name ?? `${d.id}.bin`).catch((e: Error) => toast.push(e.message, "error"));
                }}>Download</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ActionsPanel({ data, onOp }: { data: CaseDetail; onOp: (op: Op) => void }) {
  const ops = new Set(data.allowed_ops);
  const { me } = useSession();
  const s = data.case.status;
  const buttons: Array<[Op, string, ReactNode, boolean]> = [
    ["action", "Add action or remark", <LuMessageSquareText aria-hidden />, ops.has("remark") || ops.has("status") || ops.has("regulatory_action")],
    ["status", "Change status", <LuCircleCheck aria-hidden />, ops.has("status") && (TRANSITIONS[s] ?? []).length > 0],
    ["assign", "Assign officer", <LuUserCheck aria-hidden />, ops.has("assign") && s !== "DISPOSED"],
    ["transfer", "Transfer", <LuArrowRightLeft aria-hidden />, ops.has("transfer") && s !== "DISPOSED"],
    ["escalate", "Escalate", <LuArrowUp aria-hidden />, ops.has("escalate") && s !== "DISPOSED" && s !== "ESCALATED"],
    ["deescalate", "Return from escalation", <LuRotateCcw aria-hidden />, ops.has("deescalate") && s === "ESCALATED"],
    ["dispose", "Dispose", <LuCircleCheck aria-hidden />, ops.has("dispose") && s !== "DISPOSED"],
    ["reopen", "Re-open", <LuRotateCcw aria-hidden />, me?.user.role === "COMPETENT_AUTHORITY" && s === "DISPOSED"],
    ["override", "Override priority", <LuSlidersHorizontal aria-hidden />, ops.has("priority_override")],
  ];
  const available = buttons.filter((b) => b[3]);
  return (
    <Card title="Actions" subtitle={`As ${me?.user.role_label ?? "this role"}; the server re-checks every action`}>
      {available.length === 0 ? (
        <p className="text-sm text-muted">Your role cannot change this case (it is with {data.case.bureau_code}). Use an overlap alert to coordinate, or switch the demo role.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {available.map(([key, label, icon]) => (
            <Button key={key} size="sm" icon={icon} onClick={() => onOp(key)} variant={key === "action" ? "primary" : "secondary"}
              className="justify-start">{label}</Button>
          ))}
        </div>
      )}
    </Card>
  );
}

// ----------------------------------------------------------------------------- dialogs
function RemarksDialog(props: { open: boolean; title: string; confirmLabel: string; description?: ReactNode; onClose: () => void;
  submit: (remarks: string) => Promise<unknown>; onDone: () => void }) {
  const [remarks, setRemarks] = useState("");
  const { busy, error, run } = useAction();
  const toast = useToast();
  return (
    <Modal open={props.open} title={props.title} onClose={props.onClose} description={props.description}
      footer={<>
        <Button onClick={props.onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={remarks.trim().length < 5} onClick={async () => {
          const ok = await run(() => props.submit(remarks.trim()));
          if (ok !== undefined) {
            toast.push(`${props.confirmLabel}: done.`);
            setRemarks("");
            props.onDone();
          }
        }}>{props.confirmLabel}</Button>
      </>}>
      <Field label="Remarks" required hint="At least 5 characters; recorded in the case history and the audit trail.">
        {(id) => <textarea id={id} rows={3} className="field-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />}
      </Field>
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}

function OperationDialog({ op, data, onClose, onDone }: { op: Op | null; data: CaseDetail; onClose: () => void;
  onDone: (result?: ActionResult | Record<string, unknown>) => void }) {
  const ref = useRefData();
  const toast = useToast();
  const { bump } = useSession();
  const c = data.case;
  const ops = new Set(data.allowed_ops);
  const [v, setV] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, run, setError } = useAction();
  const set = (k: string) => (value: string) => setV((x) => ({ ...x, [k]: value }));
  const close = () => {
    setV({});
    setFile(null);
    setError(null);
    onClose();
  };
  if (!op) return null;
  const path = `/api/cases/${encodeURIComponent(c.id)}`;
  const remarksField = (required: boolean, label = "Remarks") => (
    <Field label={label} required={required} hint={required ? "Mandatory (at least 5 characters); kept in the case history and audit trail." : "Optional"}>
      {(id) => <textarea id={id} rows={3} className="field-input" value={v.remarks ?? ""} onChange={(e) => set("remarks")(e.target.value)} />}
    </Field>
  );
  const actionChoices = [
    ...(ops.has("remark") ? ["REMARK"] : []),
    ...(ops.has("status") ? ref.manualActions.filter((a) => a !== "REMARK") : []),
    ...(ops.has("regulatory_action") ? ref.regulatoryActions : []),
  ];
  const configs: Record<Op, { title: string; label: string; body: ReactNode; valid: boolean; send: () => Promise<unknown> }> = {
    action: {
      title: `Add action to ${c.id}`, label: "Add action",
      valid: !!v.action_type && (v.action_type !== "REMARK" || (v.remarks ?? "").trim().length > 0),
      body: <div className="space-y-3">
        <Field label="Action" required hint={ops.has("regulatory_action") ? "Regulatory actions (renewal, approval, NOC…) are checked against open complaints in every Bureau/Cell." : undefined}>
          {(id) => <SelectInput id={id} value={v.action_type ?? ""} onChange={set("action_type")} placeholder="Choose an action"
            options={actionChoices.map((a) => ({ value: a, label: `${ref.actionLabel(a)}${ref.regulatoryActions.includes(a) ? " (regulatory)" : ""}` }))} />}
        </Field>
        {remarksField(v.action_type === "REMARK", "Remarks / details")}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Next action">{(id) => <input id={id} className="field-input" value={v.next_action ?? ""} onChange={(e) => set("next_action")(e.target.value)} />}</Field>
          <Field label="Next action due">{(id) => <input id={id} type="date" className="field-input" value={v.next_action_due ?? ""} onChange={(e) => set("next_action_due")(e.target.value)} />}</Field>
        </div>
      </div>,
      send: () => api.post<ActionResult>(`${path}/actions`, { action_type: v.action_type, remarks: v.remarks || null,
        next_action: v.next_action || null, next_action_due: v.next_action_due || null }),
    },
    status: {
      title: "Change status", label: "Change status", valid: !!v.status,
      body: <div className="space-y-3">
        <Field label="New status" required hint="Transfer, escalation and disposal have their own actions.">
          {(id) => <SelectInput id={id} value={v.status ?? ""} onChange={set("status")} placeholder="Choose"
            options={(TRANSITIONS[c.status] ?? []).map((s) => ({ value: s, label: ref.statusLabel(s) }))} />}
        </Field>
        {remarksField(false)}
      </div>,
      send: () => api.post(`${path}/status`, { status: v.status, remarks: v.remarks || null }),
    },
    assign: {
      title: "Assign officer", label: "Assign", valid: !!v.officer_id,
      body: <div className="space-y-3">
        <Field label={`Officer (${c.bureau_code})`} required>
          {(id) => <SelectInput id={id} value={v.officer_id ?? ""} onChange={set("officer_id")} placeholder="Choose an officer"
            options={data.officers.map((o) => ({ value: o.id, label: `${o.display_name}${o.id === c.assigned_officer_id ? " (current)" : ""}` }))} />}
        </Field>
        {remarksField(false)}
      </div>,
      send: () => api.post(`${path}/assign`, { officer_id: v.officer_id, remarks: v.remarks || null }),
    },
    transfer: {
      title: "Transfer to another Bureau/Cell", label: "Transfer", valid: !!v.to_bureau && (v.remarks ?? "").trim().length >= 5,
      body: <div className="space-y-3">
        <Field label="Transfer to" required>
          {(id) => <SelectInput id={id} value={v.to_bureau ?? ""} onChange={set("to_bureau")} placeholder="Choose"
            options={ref.bureaus.filter((b) => b.code !== c.bureau_code).map((b) => ({ value: b.code, label: `${b.code}, ${b.name}` }))} />}
        </Field>
        {remarksField(true)}
      </div>,
      send: () => api.post(`${path}/transfer`, { to_bureau: v.to_bureau, remarks: v.remarks }),
    },
    escalate: { title: "Escalate to the Competent Authority", label: "Escalate", valid: (v.remarks ?? "").trim().length >= 5,
      body: remarksField(true), send: () => api.post(`${path}/escalate`, { remarks: v.remarks }) },
    deescalate: { title: "Return the case from escalation", label: "Return to processing", valid: (v.remarks ?? "").trim().length >= 5,
      body: remarksField(true), send: () => api.post(`${path}/deescalate`, { remarks: v.remarks }) },
    reopen: { title: "Re-open the case", label: "Re-open", valid: (v.remarks ?? "").trim().length >= 5,
      body: remarksField(true), send: () => api.post(`${path}/reopen`, { remarks: v.remarks }) },
    dispose: {
      title: "Dispose of the case", label: "Dispose", valid: !!v.outcome && (v.remarks ?? "").trim().length >= 5,
      body: <div className="space-y-3">
        <Field label="Outcome" required>
          {(id) => <SelectInput id={id} value={v.outcome ?? ""} onChange={set("outcome")} placeholder="Choose the outcome"
            options={Object.entries(ref.outcomes).map(([k, label]) => ({ value: k, label }))} />}
        </Field>
        {remarksField(true, "Disposal remarks")}
      </div>,
      send: () => api.post(`${path}/dispose`, { outcome: v.outcome, remarks: v.remarks }),
    },
    override: {
      title: "Override priority band", label: "Save override", valid: (v.reason ?? "").trim().length >= 5,
      body: <div className="space-y-3">
        <p className="text-sm text-muted">Computed: {humanize(data.priority.band)} ({data.priority.score.toFixed(1)}). Current: {humanize(data.priority.effective_band)}.</p>
        <Field label="New band">
          {(id) => <SelectInput id={id} value={v.band ?? ""} onChange={set("band")} placeholder="Clear override (use computed band)"
            options={["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((b) => ({ value: b, label: humanize(b) }))} />}
        </Field>
        <Field label="Reason" required hint="Logged with the previous and new band, officer, Bureau/Cell and time.">
          {(id) => <textarea id={id} rows={3} className="field-input" value={v.reason ?? ""} onChange={(e) => set("reason")(e.target.value)} />}
        </Field>
      </div>,
      send: () => api.post(`${path}/priority-override`, { band: v.band || null, reason: v.reason }),
    },
    document: {
      title: "Add document reference", label: "Add document", valid: (v.title ?? "").trim().length >= 3,
      body: <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Type" required>{(id) => <SelectInput id={id} value={v.doc_type ?? "LETTER"} onChange={set("doc_type")}
            options={DOC_TYPES.map((d) => ({ value: d, label: humanize(d) }))} />}</Field>
          <Field label="Reference number">{(id) => <input id={id} className="field-input" value={v.reference_no ?? ""} onChange={(e) => set("reference_no")(e.target.value)} />}</Field>
        </div>
        <Field label="Title" required>{(id) => <input id={id} className="field-input" value={v.title ?? ""} onChange={(e) => set("title")(e.target.value)} />}</Field>
        <Field label="File (optional)" hint="PDF, PNG, JPG or TXT, up to 10 MB. Stored locally with a SHA-256 checksum.">
          {(id) => <input id={id} type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
        </Field>
      </div>,
      send: () => {
        const form = new FormData();
        form.set("doc_type", v.doc_type ?? "LETTER");
        form.set("title", v.title ?? "");
        if (v.reference_no) form.set("reference_no", v.reference_no);
        if (file) form.set("file", file);
        return api.upload(`${path}/documents`, form);
      },
    },
  };
  const cfg = configs[op];
  return (
    <Modal open title={cfg.title} onClose={close}
      footer={<>
        <Button onClick={close}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!cfg.valid} onClick={async () => {
          const result = await run(cfg.send);
          if (result !== undefined) {
            toast.push(`${cfg.label}: saved for ${c.id}.`);
            bump();
            setV({});
            setFile(null);
            onDone(result as Record<string, unknown>);
          }
        }}>{cfg.label}</Button>
      </>}>
      {cfg.body}
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}
