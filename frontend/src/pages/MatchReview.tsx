import { useEffect, useState } from "react";
import { LuBuilding2, LuCheck, LuCirclePlus, LuX } from "react-icons/lu";
import { api } from "../api/client";
import type { Candidate, ReviewPage, ReviewRow } from "../api/models";
import { useTitle } from "../components/layout";
import {
  Button, Chip, Disclosure, Empty, ErrorState, Field, InlineError, Loading, Modal, PageHeader, Pagination, SelectInput, Tabs,
} from "../components/ui";
import { fmtDateTime, fmtPct, humanize } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link, setQuery, useLocation } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

const STATUSES = ["PENDING", "CONFIRMED", "REJECTED", "NEW_INSTITUTION"] as const;
type Pending = { kind: "confirm" | "reject"; review: ReviewRow; candidate: Candidate } | { kind: "new"; review: ReviewRow } | null;

export function MatchReviewPage() {
  useTitle("Institution Match Review");
  const { params } = useLocation();
  const { can } = useSession();
  const status = (params.get("status") ?? "PENDING") as (typeof STATUSES)[number];
  const page = Number(params.get("page") ?? "1") || 1;
  const focus = params.get("focus");
  const { data, error, loading, reload } = useApi<ReviewPage>("/api/match-reviews", { status: [status], page, page_size: 20 });
  const [pending, setPending] = useState<Pending>(null);
  useEffect(() => {
    if (focus && data) document.getElementById(focus)?.scrollIntoView({ block: "center" });
  }, [focus, data]);
  return (
    <div>
      <PageHeader title="Institution match review"
        subtitle="Complaint records whose institution name could not be linked automatically. Confirm the right institution, reject wrong candidates (this trains future matching) or create a new Institution Master record." />
      {!can("match.review") && <p className="mb-3 rounded-md border border-line bg-tint px-3 py-2 text-sm text-muted">Your demo role can view the queue but not decide matches.</p>}
      <Tabs value={status} onChange={(s) => setQuery({ status: s === "PENDING" ? null : s, page: null, focus: null })} className="mb-4"
        tabs={STATUSES.map((s) => ({ value: s, label: humanize(s), count: data?.counts[s] ?? 0 }))} />
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && data.items.length === 0 && <Empty title={`No ${humanize(status).toLowerCase()} reviews`}>{status === "PENDING" ? "Every complaint is linked to an institution." : ""}</Empty>}
      <div className="space-y-3">
        {data?.items.map((r) => <ReviewCard key={r.id} r={r} focused={r.id === focus} canDecide={can("match.review")} onPick={setPending} />)}
      </div>
      {data && data.total > 20 && <Pagination page={page} pageSize={20} total={data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />}
      <DecisionDialog pending={pending} onClose={() => setPending(null)} onDone={() => {
        setPending(null);
        reload();
      }} />
    </div>
  );
}

function ReviewCard({ r, focused, canDecide, onPick }: { r: ReviewRow; focused: boolean; canDecide: boolean; onPick: (p: Pending) => void }) {
  const candidates = r.candidates as unknown as Candidate[];
  return (
    <section id={r.id} className={`rounded-lg border bg-white p-4 ${focused ? "border-blue ring-2 ring-blue/30" : "border-line"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted">{r.id}, {humanize(r.source_type)}, {fmtDateTime(r.created_at)}</p>
          <h2 className="mt-0.5 text-lg font-semibold text-navy-ink">“{r.raw_name}”</h2>
          <p className="text-sm text-muted">{[r.raw_address, r.raw_state, r.raw_pincode, r.raw_permanent_id].filter(Boolean).join(", ") || "No address hints"}</p>
          {r.source_ref && (
            <p className="mt-1 text-sm">From case <Link to={`/cases/${r.source_ref}`} className="font-semibold">{r.source_ref}</Link>
              {r.case_subject && <span className="text-muted">: {r.case_subject}</span>}</p>
          )}
        </div>
        <Chip tone={r.status === "PENDING" ? "orange" : r.status === "REJECTED" ? "red" : "green"}>{humanize(r.status)}</Chip>
      </div>
      {r.status !== "PENDING" && r.decided_by && (
        <p className="mt-2 text-sm text-ink">Decided by {r.decided_by}, {fmtDateTime(r.decided_at)}
          {r.decided_institution_id && <> → <Link to={`/institutions/${r.decided_institution_id}`}>{r.decided_institution_id}</Link></>}
          {r.remarks && <span className="text-muted">. {r.remarks}</span>}</p>
      )}
      {candidates.length > 0 && candidates[0].confidence < 0.55 && (
        <p className="mt-2 text-sm text-orange-ink">No candidate reaches the review threshold: this may be an institution missing from the Institution Master.</p>
      )}
      <ul className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
        {candidates.filter((c, i) => i === 0 || c.confidence >= 0.05).slice(0, 4).map((c) => (
          <li key={c.institution_id} className="rounded-md border border-line p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <Link to={`/institutions/${c.institution_id}`} className="font-semibold"><LuBuilding2 aria-hidden className="mr-1 inline" />{c.name}</Link>
                <p className="text-xs text-muted">{c.permanent_id ?? "No Permanent ID"}, {c.district ? `${c.district}, ` : ""}{c.state}{c.pincode ? `, ${c.pincode}` : ""}</p>
              </div>
              <span className={`num text-lg font-bold ${c.band === "HIGH" ? "text-green-ink" : c.band === "MEDIUM" ? "text-orange-ink" : "text-muted"}`}>{fmtPct(c.confidence)}</span>
            </div>
            <ul className="mt-2 flex flex-wrap gap-1">
              {c.factors.map((f) => <li key={f.factor + f.label} className="max-w-full"><Chip wrap tone={f.effect === "-" ? "red" : "neutral"}>{f.label}</Chip></li>)}
            </ul>
            {canDecide && r.status === "PENDING" && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="primary" icon={<LuCheck aria-hidden />} onClick={() => onPick({ kind: "confirm", review: r, candidate: c })}>Confirm</Button>
                <Button size="sm" icon={<LuX aria-hidden />} onClick={() => onPick({ kind: "reject", review: r, candidate: c })}>Not this one</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {candidates.length === 0 && <p className="mt-2 text-sm text-muted">No candidate remains.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canDecide && r.status !== "CONFIRMED" && r.status !== "NEW_INSTITUTION" && (
          <Button size="sm" icon={<LuCirclePlus aria-hidden />} onClick={() => onPick({ kind: "new", review: r })}>Create a new institution</Button>
        )}
        {candidates[0] && (
          <Disclosure summary="Model features for the best candidate">
            <ul className="grid grid-cols-2 gap-x-4 text-xs sm:grid-cols-3">
              {Object.entries((candidates[0] as unknown as { features: Record<string, number> }).features ?? {}).map(([k, v]) => (
                <li key={k} className="flex justify-between gap-2"><span className="text-muted">{k.replace(/_/g, " ")}</span><span className="num">{v.toFixed(2)}</span></li>
              ))}
            </ul>
          </Disclosure>
        )}
      </div>
    </section>
  );
}

function DecisionDialog({ pending, onClose, onDone }: { pending: Pending; onClose: () => void; onDone: () => void }) {
  const ref = useRefData();
  const toast = useToast();
  const { bump } = useSession();
  const { busy, error, run, setError } = useAction();
  const [remarks, setRemarks] = useState("");
  const [fields, setFields] = useState({ name: "", state: "", district: "", pincode: "", permanent_id: "", address: "" });
  useEffect(() => {
    if (pending?.kind === "new") {
      setFields({ name: pending.review.raw_name, state: pending.review.raw_state ?? "", district: "", pincode: pending.review.raw_pincode ?? "",
        permanent_id: pending.review.raw_permanent_id ?? "", address: pending.review.raw_address ?? "" });
    }
    setRemarks("");
    setError(null);
  }, [pending, setError]);
  if (!pending) return null;
  const base = `/api/match-reviews/${pending.review.id}`;
  const title = pending.kind === "confirm" ? `Confirm ${pending.candidate.name}` : pending.kind === "reject" ? `Reject ${pending.candidate.name}` : "Create a new institution";
  const valid = pending.kind === "reject" ? remarks.trim().length >= 5 : pending.kind === "new" ? fields.name.trim().length >= 4 && !!fields.state : true;
  const send = () => {
    if (pending.kind === "confirm") return api.post(`${base}/confirm`, { institution_id: pending.candidate.institution_id, remarks: remarks || null });
    if (pending.kind === "reject") return api.post(`${base}/reject`, { institution_id: pending.candidate.institution_id, remarks });
    return api.post(`${base}/new-institution`, { ...Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, v.trim() || null])), remarks: remarks || null });
  };
  return (
    <Modal open title={title} onClose={onClose}
      description={pending.kind === "confirm" ? `“${pending.review.raw_name}” becomes a confirmed alias and the case is linked. Overlap detection then runs for the case.`
        : pending.kind === "reject" ? "The pairing is remembered as wrong, so it is down-weighted in future matching." : "Use this only when the institution is genuinely missing from the Institution Master."}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!valid} onClick={async () => {
          const out = await run(send);
          if (out !== undefined) {
            const alerts = (out as { overlap_alerts?: Array<{ alert_id: string }> }).overlap_alerts ?? [];
            toast.push(`${title}: saved.${alerts.length ? ` Overlap alerts: ${alerts.map((a) => a.alert_id).join(", ")}.` : ""}`);
            bump();
            onDone();
          }
        }}>{pending.kind === "confirm" ? "Confirm match" : pending.kind === "reject" ? "Reject candidate" : "Create institution"}</Button>
      </>}>
      {pending.kind === "new" && (
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Name" required className="sm:col-span-2">{(id) => <input id={id} className="field-input" value={fields.name} onChange={(e) => setFields({ ...fields, name: e.target.value })} />}</Field>
          <Field label="State" required>{(id) => <SelectInput id={id} value={fields.state} onChange={(v) => setFields({ ...fields, state: v })} placeholder="Choose"
            options={ref.states.map((s) => ({ value: s.name, label: s.name }))} />}</Field>
          <Field label="District">{(id) => <input id={id} className="field-input" value={fields.district} onChange={(e) => setFields({ ...fields, district: e.target.value })} />}</Field>
          <Field label="PIN code">{(id) => <input id={id} className="field-input" value={fields.pincode} onChange={(e) => setFields({ ...fields, pincode: e.target.value })} />}</Field>
          <Field label="AICTE Permanent ID">{(id) => <input id={id} className="field-input" value={fields.permanent_id} onChange={(e) => setFields({ ...fields, permanent_id: e.target.value })} />}</Field>
          <Field label="Address" className="sm:col-span-2">{(id) => <input id={id} className="field-input" value={fields.address} onChange={(e) => setFields({ ...fields, address: e.target.value })} />}</Field>
        </div>
      )}
      <Field label="Remarks" required={pending.kind === "reject"} hint={pending.kind === "reject" ? "Mandatory: explain why this is a different institution." : "Optional"}>
        {(id) => <textarea id={id} rows={3} className="field-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />}
      </Field>
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}
