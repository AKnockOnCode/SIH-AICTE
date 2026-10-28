import { useMemo, useState, type ReactNode } from "react";
import { LuCheck, LuCombine, LuEye, LuGitCompareArrows, LuLink, LuRotateCcw, LuScale, LuX } from "react-icons/lu";
import { api } from "../api/client";
import type { LeadRecommendation, MemberCase, OverlapDetail, PairSignal } from "../api/models";
import { useTitle } from "../components/layout";
import {
  BandChip, BureauTag, Button, Card, Chip, Disclosure, ErrorState, Field, InlineError, KeyValues, Loading, Modal, SelectInput, StatusChip,
  TierChip,
} from "../components/ui";
import { fmtDate, fmtDateTime, fmtPct, humanize, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { bureauColor, C } from "../lib/theme";

type Dialog = "link" | "review" | "resolve" | "dismiss" | "reopen" | "accept" | "override" | "merge" | "coordinate" | null;

function focusPair(d: OverlapDetail): [string, string] {
  const byId = new Map(d.members.map((m) => [m.id, m]));
  const pairs = d.pairs as unknown as PairSignal[];
  const trigger = d.alert.trigger_case_id;
  const ranked = [...pairs].sort((p, q) => {
    const score = (x: PairSignal) => {
      const other = byId.get(x.a === trigger ? x.b : x.a);
      return (x.a === trigger || x.b === trigger ? 4 : 0) + (other && other.status !== "DISPOSED" ? 2 : 0) + x.score
        + (other ? other.severity_level / 10 + Number(other.received_date.replace(/-/g, "")) / 1e9 : 0);
    };
    return score(q) - score(p);
  });
  if (ranked.length) {
    const p = ranked[0];
    return p.a === trigger || byId.get(p.a)?.role === "TRIGGER" ? [p.a, p.b] : [p.b, p.a];
  }
  const ids = d.members.map((m) => m.id);
  return [ids[0], ids[1] ?? ids[0]];
}

export function OverlapDetailPage({ id }: { id: string }) {
  useTitle("Overlap Alert", id);
  const { data, error, loading, reload } = useApi<OverlapDetail>(`/api/overlaps/${encodeURIComponent(id)}`);
  const [pick, setPick] = useState<[string, string] | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const pair = useMemo(() => (data ? pick ?? focusPair(data) : null), [data, pick]);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || !pair) return loading ? <Loading /> : null;
  const a = data.alert;
  const conflict = a.tier === "CONFLICT";
  const left = data.members.find((m) => m.id === pair[0]) ?? data.members[0];
  const right = data.members.find((m) => m.id === pair[1]) ?? data.members[1] ?? data.members[0];
  const pairs = data.pairs as unknown as PairSignal[];
  const signal = pairs.find((p) => (p.a === left.id && p.b === right.id) || (p.a === right.id && p.b === left.id));
  const rec = data.recommendation as unknown as LeadRecommendation;
  const closed = a.status === "RESOLVED" || a.status === "DISMISSED";
  return (
    <div>
      <div className={`mb-4 rounded-lg border-2 px-4 py-4 text-center ${conflict ? "border-red bg-red-soft" : a.tier === "DUPLICATE" ? "border-green bg-green-soft" : "border-orange bg-orange-soft"}`}>
        <p className={`text-xl font-bold ${conflict ? "text-red-ink" : a.tier === "DUPLICATE" ? "text-green-ink" : "text-orange-ink"}`}>{a.headline}</p>
        <p className="mt-1 text-sm text-ink">
          <Link to={`/institutions/${a.institution_id}`} className="font-semibold">{a.institution_name}</Link>
          {" "}({String(data.institution.permanent_id ?? "no Permanent ID")}), {a.cases.length} cases across {a.bureaus.join(" and ")}
        </p>
        <p className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <TierChip tier={a.tier} />
          <Chip tone={a.status === "OPEN" ? "orange" : a.status === "UNDER_REVIEW" ? "blue" : "neutral"}>{humanize(a.status)}</Chip>
          <Chip tone="neutral">{a.id}, score {a.score.toFixed(2)}</Chip>
          {a.rules.map((r) => <Chip key={r} tone="neutral">Rule {r}</Chip>)}
          {a.demo_tag === "INSTITUTION_A" && <Chip tone="navy">Institution A demo story</Chip>}
        </p>
      </div>

      <section aria-label="Side-by-side comparison" className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[1fr_auto_1fr]">
        <CaseCard m={left} />
        <div className="flex flex-col items-center justify-center gap-2 py-2">
          <div className="hidden h-0 w-24 border-t-[3px] border-dashed border-red lg:block" aria-hidden />
          <span className="rounded-full border-2 border-red bg-white px-3 py-1 text-xs font-bold text-red-ink">same institution</span>
          <div className="hidden h-0 w-24 border-t-[3px] border-dashed border-red lg:block" aria-hidden />
        </div>
        <CaseCard m={right} />
      </section>

      <Card className="mt-4" title="Why these two cases were flagged" subtitle="Institution match reasoning, category and text similarity, timing and the triggering action">
        {signal ? (
          <>
            <ul className="space-y-1.5 text-sm">
              {signal.rules.map((r) => <li key={r.code} className="flex gap-2"><Chip tone={conflict ? "red" : "orange"}>{r.code}</Chip><span>{r.text}</span></li>)}
            </ul>
            <div className="mt-3">
              <KeyValues cols={3} items={[
                ["Institution match", `${left.id}: ${humanize(left.match_status)} ${left.match_confidence !== null ? fmtPct(left.match_confidence) : ""}; ${right.id}: ${humanize(right.match_status)} ${right.match_confidence !== null ? fmtPct(right.match_confidence) : ""}`],
                ["Names as received", `“${left.institution_name_raw}” / “${right.institution_name_raw}”`],
                ["Text similarity", fmtPct(signal.text_similarity)],
                ["Received apart", `${signal.days_apart} days`],
                ["Same category / issue family", `${signal.same_category ? "Yes" : "No"} / ${signal.same_family ? "Yes" : "No"}`],
                ["Different Bureaus/Cells", signal.cross_bureau ? "Yes" : "No"],
                ["Same external reference", signal.external_ref_match ? "Yes" : "No"],
                ["Triggering action", signal.favourable_action ? `${humanize(signal.favourable_action.action_type)} on ${signal.favourable_action.case_id} by ${signal.favourable_action.bureau_code}, ${fmtDateTime(signal.favourable_action.action_at)}` : "—"],
              ]} />
            </div>
          </>
        ) : <p className="text-sm text-muted">These two cases are not a directly flagged pair; both are linked to this alert through other members.</p>}
        <p className="mt-3 rounded-md bg-tint px-3 py-2 text-sm text-ink">{data.explanation}</p>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7" title={`All ${data.members.length} cases in this alert`} subtitle="Choose two to compare side by side">
          <ul className="divide-y divide-line">
            {data.members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                <span className="h-8 w-1 rounded" style={{ background: bureauColor(m.bureau_code) }} aria-hidden />
                <Link to={`/cases/${m.id}`} className="font-semibold">{m.id}</Link>
                {m.role === "TRIGGER" && <Chip tone="red">Trigger</Chip>}
                <span className="min-w-40 flex-1">{m.category_label}<span className="block text-xs text-muted">{m.latest_action ?? "—"}</span></span>
                <StatusChip status={m.status} />
                <span className="flex gap-1">
                  <Button size="sm" variant={pair[0] === m.id ? "primary" : "secondary"} aria-pressed={pair[0] === m.id}
                    aria-label={`Show ${m.id} on the left`} onClick={() => setPick([m.id, pair[1] === m.id ? pair[0] : pair[1]])}>Left</Button>
                  <Button size="sm" variant={pair[1] === m.id ? "primary" : "secondary"} aria-pressed={pair[1] === m.id}
                    aria-label={`Show ${m.id} on the right`} onClick={() => setPick([pair[0] === m.id ? pair[1] : pair[0], m.id])}>Right</Button>
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <LeadCard rec={rec} decided={data.decision} onAccept={() => setDialog("accept")} onOverride={() => setDialog("override")}
          canDecide={data.permissions.can_decide && !closed} />

        <Card className="xl:col-span-7" title="Coordinate" subtitle={`Next step: ${a.next_step ?? "review the cases together."}`}>
          <div className="flex flex-wrap gap-2">
            {data.permissions.can_act && !closed && <Button icon={<LuLink aria-hidden />} onClick={() => setDialog("link")}>Link cases</Button>}
            {data.permissions.can_act && a.status === "OPEN" && <Button icon={<LuEye aria-hidden />} onClick={() => setDialog("review")}>Mark for review</Button>}
            {a.tier === "DUPLICATE" && data.permissions.can_merge_duplicates && !closed && (
              <Button variant="primary" icon={<LuCombine aria-hidden />} onClick={() => setDialog("merge")}>Merge into Master Case</Button>)}
            {a.tier !== "DUPLICATE" && data.permissions.can_create_coordination_master && !closed && (
              <Button variant="primary" icon={<LuCombine aria-hidden />} onClick={() => setDialog("coordinate")}>Create coordinated Master Case</Button>)}
            {data.permissions.can_decide && !closed && <Button icon={<LuCheck aria-hidden />} onClick={() => setDialog("resolve")}>Resolve</Button>}
            {data.permissions.can_decide && !closed && <Button variant="secondary" icon={<LuX aria-hidden />} onClick={() => setDialog("dismiss")}>Dismiss as not an overlap</Button>}
            {data.permissions.can_decide && closed && <Button icon={<LuRotateCcw aria-hidden />} onClick={() => setDialog("reopen")}>Re-open</Button>}
          </div>
          {!data.permissions.can_act && !data.permissions.can_decide && (
            <p className="mt-2 text-sm text-muted">Your role can view this alert but not act on it. Bureau/Cell officers involved, the Regional Office and the Competent Authority can act.</p>
          )}
          {conflict && !data.permissions.can_decide && data.permissions.can_act && (
            <p className="mt-2 text-sm text-muted">Resolving a cross-bureau conflict or deciding its lead is reserved for the Competent Authority.</p>
          )}
          <Disclosure summary={`Links (${data.links.length}) and Master Cases (${data.master_cases.length})`}>
            {data.links.length === 0 && data.master_cases.length === 0 && <p className="text-sm text-muted">None yet.</p>}
            <ul className="space-y-1 text-sm">
              {data.links.map((l) => (
                <li key={String(l.id)}>{String(l.case_a)} ↔ {String(l.case_b)}: {humanize(String(l.link_type))}{Number(l.active) ? "" : " (removed)"}
                  <span className="text-xs text-muted"> by {String(l.created_by)}, {fmtDateTime(String(l.created_at))}</span></li>
              ))}
              {data.master_cases.map((m) => (
                <li key={String(m.id)}><Link to={`/master-cases/${String(m.id)}`}>{String(m.id)}</Link>: {String(m.title)} ({humanize(String(m.kind))}, {humanize(String(m.status))})</li>
              ))}
            </ul>
          </Disclosure>
        </Card>
        <Card className="xl:col-span-5" title="Decision record and audit">
          <KeyValues cols={1} items={[
            ["Lead decision", data.decision.decided_lead ? `${String(data.decision.lead_decision)}: ${String(data.decision.decided_lead)} by ${String(data.decision.decided_by)} (${roleLabel(String(data.decision.decided_role))}), ${fmtDateTime(String(data.decision.decided_at))}` : "Not decided"],
            ["Decision remarks", String(data.decision.decision_remarks ?? "—")],
            ["Status remarks", data.decision.status_remarks ? `${String(data.decision.status_remarks)} (${String(data.decision.status_by)}, ${fmtDateTime(String(data.decision.status_at))})` : "—"],
          ]} />
          <ol className="mt-3 space-y-1 border-t border-line pt-2 text-xs">
            {data.audit.map((e) => (
              <li key={String(e.seq)} className="flex justify-between gap-2"><span><strong>{humanize(String(e.action))}</strong> by {String(e.actor_label)}{e.remarks ? `: ${String(e.remarks)}` : ""}</span>
                <span className="shrink-0 text-muted">#{String(e.seq)}</span></li>
            ))}
          </ol>
          <Link to={`/audit?entity_id=${a.id}`} className="mt-2 inline-block text-sm">Full audit trail</Link>
        </Card>
      </div>
      <OverlapDialog kind={dialog} data={data} pair={pair} onClose={() => setDialog(null)} onDone={() => {
        setDialog(null);
        reload();
      }} />
    </div>
  );
}

function CaseCard({ m }: { m: MemberCase }) {
  const color = bureauColor(m.bureau_code);
  return (
    <article className="rounded-lg border-2 bg-white p-4" style={{ borderColor: color }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link to={`/cases/${m.id}`} className="text-lg font-bold no-underline hover:underline" style={{ color: m.bureau_code === "PGRC" ? C.orangeStrong : color }}>{m.id}</Link>
          <p className="text-sm font-semibold text-ink">{m.latest_action ?? humanize(m.status)}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {m.role === "TRIGGER" ? <Chip tone="red">Triggering case</Chip> : <Chip tone="neutral">Member</Chip>}
          <BureauTag code={m.bureau_code} />
        </div>
      </div>
      <p className="mt-2 text-sm text-ink">{m.category_label}: <span className="text-muted">{m.subject}</span></p>
      <div className="mt-3">
        <KeyValues items={[
          ["Status", <span className="flex flex-wrap items-center gap-1"><StatusChip status={m.status} />{m.outcome && <Chip tone="neutral">{humanize(m.outcome)}</Chip>}</span>],
          ["Severity / priority", <span className="flex items-center gap-1">{m.severity_level}/5 <BandChip band={m.effective_band} score={m.priority_score} /></span>],
          ["Received", fmtDate(m.received_date)],
          ["SLA", <span className={m.sla_state === "OVERDUE" ? "font-semibold text-red-ink" : ""}>{m.sla_label}</span>],
          ["Officer", m.officer_name ?? "Unassigned"],
          ["Next action", m.next_action ? `${m.next_action}${m.next_action_due ? ` by ${fmtDate(m.next_action_due)}` : ""}` : "—"],
        ]} />
      </div>
      <p className="mt-3 text-xs text-muted">Institution as received: “{m.institution_name_raw}”, {humanize(m.match_status)}{m.match_confidence !== null ? ` (${fmtPct(m.match_confidence)})` : ""}</p>
      {m.latest_actions.length > 0 && (
        <ol className="mt-2 space-y-1 border-t border-line pt-2 text-xs">
          {m.latest_actions.map((x, i) => (
            <li key={i}><span className="text-muted">{fmtDateTime(String(x.action_at))}</span> {String(x.label)}{x.remarks ? `: ${String(x.remarks)}` : ""}</li>
          ))}
        </ol>
      )}
    </article>
  );
}

function LeadCard({ rec, decided, canDecide, onAccept, onOverride }: { rec: LeadRecommendation; decided: Record<string, unknown>;
  canDecide: boolean; onAccept: () => void; onOverride: () => void }) {
  const ref = useRefData();
  return (
    <Card className="xl:col-span-5" title={<span className="flex items-center gap-2"><LuScale aria-hidden className="text-navy" />Suggested lead: {rec.recommended ?? "—"}</span>}
      subtitle={rec.recommended ? ref.bureauName(rec.recommended) : undefined}
      actions={canDecide && !decided.decided_lead && (<>
        <Button size="sm" variant="primary" onClick={onAccept}>Accept</Button>
        <Button size="sm" onClick={onOverride}>Override</Button>
      </>)}>
      {decided.decided_lead ? <p className="mb-2 text-sm font-semibold text-green-ink">Agreed lead: {String(decided.decided_lead)} ({humanize(String(decided.lead_decision))})</p> : null}
      <table className="data-table">
        <thead><tr><th scope="col">Bureau</th><th scope="col" className="num">Subject</th><th scope="col" className="num">Handling</th>
          <th scope="col" className="num">Actions</th><th scope="col" className="num">Workload</th><th scope="col" className="num">Score</th></tr></thead>
        <tbody>
          {rec.scores.map((s) => (
            <tr key={s.bureau}>
              <td><BureauTag code={s.bureau} /></td>
              <td className="num">{s.subject_points}</td>
              <td className="num">{s.handler_points}</td>
              <td className="num">{s.action_points}</td>
              <td className="num" title={`${s.open_per_officer} open cases per officer (${s.load_ratio}x average)`}>x{s.workload_factor.toFixed(2)}</td>
              <td className="num font-semibold">{s.score}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted">{rec.rationale.map((r) => <li key={r}>{r}</li>)}</ul>
      <Disclosure summary="Scoring notes per case">
        <ul className="space-y-0.5 text-xs text-ink">{rec.scores.flatMap((s) => s.notes.map((n) => <li key={s.bureau + n}>{s.bureau}: {n}</li>))}</ul>
      </Disclosure>
    </Card>
  );
}

function OverlapDialog({ kind, data, pair, onClose, onDone }: { kind: Dialog; data: OverlapDetail; pair: [string, string]; onClose: () => void; onDone: () => void }) {
  const ref = useRefData();
  const toast = useToast();
  const { bump } = useSession();
  const { busy, error, run, setError } = useAction();
  const [remarks, setRemarks] = useState("");
  const [linkType, setLinkType] = useState<string>(data.alert.tier);
  const [cases, setCases] = useState<string[]>(pair);
  const [bureau, setBureau] = useState("");
  const [title, setTitle] = useState("");
  if (!kind) return null;
  const base = `/api/overlaps/${data.alert.id}`;
  const close = () => {
    setRemarks("");
    setError(null);
    onClose();
  };
  const remarksOk = remarks.trim().length >= 5;
  const caseOptions = data.members.map((m) => ({ value: m.id, label: `${m.id} (${m.bureau_code}, ${m.category_label})` }));
  const caseChecks = (
    <fieldset>
      <legend className="mb-1 text-xs font-semibold text-ink">Cases <span className="text-red-ink">*</span></legend>
      <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {data.members.map((m) => (
          <label key={m.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cases.includes(m.id)} onChange={(e) => setCases(e.target.checked ? [...cases, m.id] : cases.filter((x) => x !== m.id))} />
            {m.id} <span className="text-xs text-muted">{m.bureau_code}, {m.category_label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
  const remarksField = (required: boolean, hint?: string) => (
    <Field label="Remarks" required={required} hint={hint ?? (required ? "Mandatory: recorded with your role, Bureau/Cell and time in the audit trail." : "Optional")}>
      {(id) => <textarea id={id} rows={3} className="field-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />}
    </Field>
  );
  const cfg: Record<Exclude<Dialog, null>, { title: string; label: string; body: ReactNode; valid: boolean; send: () => Promise<unknown> }> = {
    link: {
      title: "Link two cases", label: "Link cases", valid: cases.length === 2 && cases[0] !== cases[1],
      body: <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Case A" required>{(id) => <SelectInput id={id} value={cases[0] ?? ""} onChange={(v) => setCases([v, cases[1]])} options={caseOptions} />}</Field>
          <Field label="Case B" required>{(id) => <SelectInput id={id} value={cases[1] ?? ""} onChange={(v) => setCases([cases[0], v])} options={caseOptions} />}</Field>
        </div>
        <Field label="Link type" required>{(id) => <SelectInput id={id} value={linkType} onChange={setLinkType}
          options={["DUPLICATE", "RELATED", "CONFLICT"].map((t) => ({ value: t, label: humanize(t) }))} />}</Field>
        {remarksField(false)}
      </div>,
      send: () => api.post(`${base}/link`, { case_a: cases[0], case_b: cases[1], link_type: linkType, remarks: remarks || null }),
    },
    review: { title: "Mark for review", label: "Mark for review", valid: remarksOk, body: remarksField(true),
      send: () => api.post(`${base}/status`, { status: "UNDER_REVIEW", remarks }) },
    resolve: { title: "Resolve the alert", label: "Resolve", valid: remarksOk,
      body: remarksField(true, "Record how the cases were coordinated (e.g. joint decision, renewal held pending findings)."),
      send: () => api.post(`${base}/status`, { status: "RESOLVED", remarks }) },
    dismiss: { title: "Dismiss the alert", label: "Dismiss", valid: remarksOk,
      body: remarksField(true, "Explain why this is not an overlap. Dismissed alerts are kept and can be re-opened."),
      send: () => api.post(`${base}/status`, { status: "DISMISSED", remarks }) },
    reopen: { title: "Re-open the alert", label: "Re-open", valid: remarksOk, body: remarksField(true),
      send: () => api.post(`${base}/status`, { status: "OPEN", remarks }) },
    accept: { title: `Accept ${String((data.recommendation as unknown as LeadRecommendation).recommended)} as lead`, label: "Accept lead", valid: true,
      body: <div className="space-y-2"><p className="text-sm text-muted">The lead Bureau/Cell coordinates the response. No case is reassigned automatically.</p>{remarksField(false)}</div>,
      send: () => api.post(`${base}/lead`, { decision: "ACCEPT", remarks: remarks || null }) },
    override: {
      title: "Override the suggested lead", label: "Override lead", valid: !!bureau && remarksOk,
      body: <div className="space-y-3">
        <Field label="Lead Bureau/Cell" required>{(id) => <SelectInput id={id} value={bureau} onChange={setBureau} placeholder="Choose"
          options={ref.bureaus.map((b) => ({ value: b.code, label: `${b.code}, ${b.name}` }))} />}</Field>
        {remarksField(true)}
      </div>,
      send: () => api.post(`${base}/lead`, { decision: "OVERRIDE", bureau, remarks }),
    },
    merge: {
      title: "Merge duplicates into a Master Case", label: "Merge", valid: cases.length >= 2 && remarksOk,
      body: <div className="space-y-3">
        <p className="text-sm text-muted">Non-destructive: each case keeps its ID, history and audit trail, and can be unmerged later.</p>
        {caseChecks}
        <Field label="Title (optional)">{(id) => <input id={id} className="field-input" value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        {remarksField(true)}
      </div>,
      send: () => api.post(`${base}/merge`, { case_ids: cases, kind: "DUPLICATE_MERGE", title: title || null, remarks }),
    },
    coordinate: {
      title: "Create a coordinated Master Case", label: "Create Master Case", valid: cases.length >= 2 && remarksOk,
      body: <div className="space-y-3">
        <p className="text-sm text-muted">Groups the cases under one coordinated record with one lead and one next action. Nothing is deleted or reassigned; originals stay with their Bureaus/Cells.</p>
        {caseChecks}
        <Field label="Lead Bureau/Cell">{(id) => <SelectInput id={id} value={bureau || String((data.recommendation as unknown as LeadRecommendation).recommended ?? "")}
          onChange={setBureau} options={ref.bureaus.map((b) => ({ value: b.code, label: `${b.code}, ${b.name}` }))} />}</Field>
        <Field label="Title (optional)">{(id) => <input id={id} className="field-input" value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        {remarksField(true)}
      </div>,
      send: () => api.post(`${base}/merge`, { case_ids: cases, kind: "COORDINATION", title: title || null, remarks,
        lead_bureau: bureau || (data.recommendation as unknown as LeadRecommendation).recommended }),
    },
  };
  const c = cfg[kind];
  return (
    <Modal open title={c.title} onClose={close} size={kind === "merge" || kind === "coordinate" ? "lg" : "md"}
      footer={<>
        <Button onClick={close}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!c.valid} icon={<LuGitCompareArrows aria-hidden />} onClick={async () => {
          const out = await run(c.send);
          if (out !== undefined) {
            const mc = (out as { master_case_id?: string }).master_case_id;
            toast.push(mc ? `${c.label}: ${mc} created.` : `${c.label}: saved.`);
            bump();
            setRemarks("");
            onDone();
          }
        }}>{c.label}</Button>
      </>}>
      {c.body}
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}
