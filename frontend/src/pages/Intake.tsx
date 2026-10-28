import { useEffect, useMemo, useState, type FormEvent } from "react";
import { LuBuilding2, LuCircleCheck, LuCirclePlus, LuSparkles, LuTriangleAlert, LuTrash2 } from "react-icons/lu";
import { api, ApiError } from "../api/client";
import type { Candidate, CreatedCase, IntakeIn, IntakePreview, MatchOutcome, OpenCaseBrief, PairSignal } from "../api/models";
import { useTitle } from "../components/layout";
import {
  BandChip, BureauTag, Button, Card, Chip, Empty, Field, InlineError, LinkButton, Loading, PageHeader, SelectInput, TierChip,
} from "../components/ui";
import { fmtDate, fmtPct, humanize } from "../lib/format";
import { useAction, useDebounced } from "../lib/hooks";
import { Link } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

const COMPLAINANT_TYPES = ["STUDENT", "PARENT", "FACULTY", "STAFF", "OTHER", "ANONYMOUS"];
const REFERENCE_FLAGS = ["NONE", "COURT", "VIP", "PARLIAMENT"];

interface FormState {
  institution_name: string;
  permanent_id: string;
  address: string;
  pincode: string;
  state: string;
  district: string;
  category_code: string;
  subject: string;
  description: string;
  received_date: string;
  bureau_code: string;
  channel: string;
  source_ref: string;
  external_ref: string;
  complainant_count: string;
  complainant_type: string;
  evidence_count: string;
  evidence_note: string;
  reference_flag: string;
  reference_note: string;
  assigned_officer_id: string;
}

type Decision = { kind: "CONFIRM"; institution_id: string; name: string } | { kind: "CREATE" } | { kind: "UNMATCHED" } | null;

export function IntakePage() {
  useTitle("New Complaint Intake");
  const ref = useRefData();
  const { me, can, bump, reloadReference } = useSession();
  const toast = useToast();
  const officerBureau = me?.user.role === "RB_OFFICER" || me?.user.role === "PGRC_OFFICER" ? me.user.bureau_code : null;
  const blank: FormState = {
    institution_name: "", permanent_id: "", address: "", pincode: "", state: "", district: "", category_code: "", subject: "",
    description: "", received_date: ref.today, bureau_code: officerBureau ?? "", channel: "INTAKE", source_ref: "", external_ref: "",
    complainant_count: "1", complainant_type: "STUDENT", evidence_count: "0", evidence_note: "", reference_flag: "NONE",
    reference_note: "", assigned_officer_id: "",
  };
  const [f, setF] = useState<FormState>(blank);
  const [bureauTouched, setBureauTouched] = useState(!!officerBureau);
  const [evidence, setEvidence] = useState<Array<{ title: string; reference_no: string }>>([]);
  const [decision, setDecision] = useState<Decision>(null);
  const [ackDup, setAckDup] = useState(false);
  const [created, setCreated] = useState<CreatedCase | null>(null);
  const [touched, setTouched] = useState(false);
  const { busy, error, run, setError } = useAction();
  const set = (k: keyof FormState) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  // Category drives the default Bureau/Cell (until the officer picks one).
  useEffect(() => {
    const cat = ref.categories.find((c) => c.code === f.category_code);
    if (cat && !bureauTouched) setF((x) => ({ ...x, bureau_code: cat.default_bureau, assigned_officer_id: "" }));
  }, [f.category_code, bureauTouched, ref.categories]);

  // Live institution matching as the name / identifiers are typed.
  const matchKey = useDebounced(JSON.stringify([f.institution_name, f.permanent_id, f.state, f.pincode, f.address, f.district]), 450);
  const [match, setMatch] = useState<MatchOutcome | null>(null);
  const [matching, setMatching] = useState(false);
  useEffect(() => {
    const [name, pid, state, pincode, address, district] = JSON.parse(matchKey) as string[];
    if (name.trim().length < 3 && pid.trim().length < 5) {
      setMatch(null);
      return;
    }
    let live = true;
    setMatching(true);
    api.post<MatchOutcome>("/api/institutions/match", { name: name.trim() || pid.trim(), permanent_id: pid || null, state: state || null,
      pincode: pincode || null, address: [address, district].filter(Boolean).join(", ") || null })
      .then((m) => {
        if (!live) return;
        setMatch(m);
        setDecision((d) => {
          if (d && d.kind === "CONFIRM" && m.candidates.some((c) => c.institution_id === d.institution_id)) return d;
          if (d && d.kind !== "CONFIRM") return d;
          const top = m.candidates[0];
          return m.decision === "AUTO_LINK" && top ? { kind: "CONFIRM", institution_id: top.institution_id, name: top.name } : null;
        });
      })
      .catch(() => live && setMatch(null))
      .finally(() => live && setMatching(false));
    return () => {
      live = false;
    };
  }, [matchKey]);

  const payload = useMemo<IntakeIn>(() => ({
    institution_name: f.institution_name.trim(), permanent_id: f.permanent_id.trim() || null, address: f.address.trim() || null,
    pincode: f.pincode.trim() || null, state: f.state || null, district: f.district.trim() || null, category_code: f.category_code,
    subject: f.subject.trim(), description: f.description.trim(), received_date: f.received_date, bureau_code: f.bureau_code,
    channel: f.channel, source_ref: f.source_ref.trim() || null, external_ref: f.external_ref.trim() || null,
    complainant_count: Math.max(1, Number(f.complainant_count) || 1), complainant_type: f.complainant_type,
    evidence_count: Math.max(0, Number(f.evidence_count) || 0), evidence_note: f.evidence_note.trim() || null,
    evidence_refs: evidence.filter((e) => e.title.trim().length >= 3).map((e) => ({ title: e.title.trim(), reference_no: e.reference_no.trim() || null })),
    reference_flag: f.reference_flag as IntakeIn["reference_flag"], reference_note: f.reference_note.trim() || null,
    assigned_officer_id: f.assigned_officer_id || null,
    institution_id: decision?.kind === "CONFIRM" ? decision.institution_id : null,
    match_decision: decision?.kind ?? "UNMATCHED", acknowledge_duplicates: ackDup,
  }), [f, evidence, decision, ackDup]);

  const problems: Record<string, string> = {};
  if (payload.institution_name.length < 3) problems.institution_name = "Enter the institution name as given in the complaint.";
  if (!payload.category_code) problems.category_code = "Choose a category.";
  if (payload.subject.length < 5) problems.subject = "At least 5 characters.";
  if (payload.description.length < 20) problems.description = "At least 20 characters.";
  if (!payload.bureau_code) problems.bureau_code = "Choose the Bureau/Cell.";
  if (!payload.received_date || payload.received_date > ref.today) problems.received_date = `Receipt date cannot be after today (${ref.today}).`;
  if (f.pincode && !/^\d{6}$/.test(f.pincode.trim())) problems.pincode = "A PIN code has 6 digits.";
  if (decision?.kind === "CREATE" && !f.state) problems.state = "State is required to create a new institution.";
  const ready = Object.keys(problems).length === 0;

  // Full preview (priority, SLA, duplicates/overlaps) once the form is complete.
  const previewKey = useDebounced(ready ? JSON.stringify({ ...payload, acknowledge_duplicates: false }) : "", 600);
  const [preview, setPreview] = useState<IntakePreview | null>(null);
  const [previewErr, setPreviewErr] = useState<ApiError | null>(null);
  const [previewing, setPreviewing] = useState(false);
  useEffect(() => {
    if (!previewKey) {
      setPreview(null);
      return;
    }
    let live = true;
    setPreviewing(true);
    api.post<IntakePreview>("/api/cases/preview", JSON.parse(previewKey))
      .then((p) => live && (setPreview(p), setPreviewErr(null)))
      .catch((e: ApiError) => live && setPreviewErr(e))
      .finally(() => live && setPreviewing(false));
    return () => {
      live = false;
    };
  }, [previewKey]);

  if (!can("case.create")) {
    return (
      <div>
        <PageHeader title="New complaint intake" />
        <Empty title="Your demo role cannot register complaints">Senior Management has read-only access. Switch to an officer, Regional Office or the Competent Authority role in the header.</Empty>
      </div>
    );
  }

  if (created) return <Created created={created} onAnother={() => {
    setCreated(null);
    setF(blank);
    setEvidence([]);
    setDecision(null);
    setAckDup(false);
    setTouched(false);
  }} />;

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setTouched(true);
    if (!ready || !decision) return;
    const out = await run(() => api.post<CreatedCase>("/api/cases", payload));
    if (out) {
      toast.push(`Registered ${out.case_id}.`);
      bump();
      reloadReference(); // the data-mode ribbon now says 'mixed'
      setCreated(out);
    }
  };
  const err = (k: string) => (touched ? problems[k] : undefined);
  const duplicates = preview?.duplicates ?? [];
  const officers = ref.officers.filter((o) => o.bureau_code === f.bureau_code);
  return (
    <div>
      <PageHeader title="New complaint intake"
        subtitle="Fill in the complaint as received. AgniDrishti matches the institution and checks every Bureau/Cell for duplicates and conflicts before you save." />
      <form onSubmit={submit} noValidate className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-7">
          <Card title="Institution named in the complaint">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Institution name" required error={err("institution_name")} className="sm:col-span-2" hint="As written by the complainant; abbreviations and misspellings are fine.">
                {(id) => <input id={id} className="field-input" value={f.institution_name} onChange={(e) => set("institution_name")(e.target.value)}
                  aria-invalid={!!err("institution_name")} autoComplete="off" />}
              </Field>
              <Field label="AICTE Permanent ID (if known)">{(id) => <input id={id} className="field-input" value={f.permanent_id} onChange={(e) => set("permanent_id")(e.target.value)} />}</Field>
              <Field label="State" error={err("state")}>{(id) => <SelectInput id={id} value={f.state} onChange={set("state")} placeholder="Not given"
                options={ref.states.map((s) => ({ value: s.name, label: s.name }))} invalid={!!err("state")} />}</Field>
              <Field label="District / city">{(id) => <input id={id} className="field-input" value={f.district} onChange={(e) => set("district")(e.target.value)} />}</Field>
              <Field label="PIN code" error={err("pincode")}>{(id) => <input id={id} className="field-input" inputMode="numeric" maxLength={6} value={f.pincode}
                onChange={(e) => set("pincode")(e.target.value)} aria-invalid={!!err("pincode")} />}</Field>
              <Field label="Address hints" className="sm:col-span-2">{(id) => <input id={id} className="field-input" value={f.address} onChange={(e) => set("address")(e.target.value)} />}</Field>
            </div>
          </Card>

          <Card title="Complaint">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Category" required error={err("category_code")}>{(id) => <SelectInput id={id} value={f.category_code} onChange={set("category_code")}
                placeholder="Choose a category" invalid={!!err("category_code")}
                options={ref.categories.filter((c) => c.active).map((c) => ({ value: c.code, label: `${c.label} (severity ${c.severity_level})` }))} />}</Field>
              <Field label="Date of receipt" required error={err("received_date")}>{(id) => <input id={id} type="date" className="field-input" max={ref.today}
                value={f.received_date} onChange={(e) => set("received_date")(e.target.value)} aria-invalid={!!err("received_date")} />}</Field>
              <Field label="Subject" required error={err("subject")} className="sm:col-span-2">{(id) => <input id={id} className="field-input" value={f.subject}
                maxLength={200} onChange={(e) => set("subject")(e.target.value)} aria-invalid={!!err("subject")} />}</Field>
              <Field label="Description" required error={err("description")} className="sm:col-span-2" hint="Do not include complainants’ names, phone numbers or e-mail addresses.">
                {(id) => <textarea id={id} rows={5} className="field-input" value={f.description} maxLength={5000}
                  onChange={(e) => set("description")(e.target.value)} aria-invalid={!!err("description")} />}
              </Field>
              <Field label="Bureau/Cell" required error={err("bureau_code")} hint={officerBureau ? `As a ${officerBureau} officer you register cases for ${officerBureau}.` : "Defaults to the category’s usual Bureau/Cell."}>
                {(id) => <SelectInput id={id} value={f.bureau_code} disabled={!!officerBureau} placeholder="Choose" invalid={!!err("bureau_code")}
                  onChange={(v) => { setBureauTouched(true); setF((x) => ({ ...x, bureau_code: v, assigned_officer_id: "" })); }}
                  options={ref.bureaus.map((b) => ({ value: b.code, label: `${b.code}, ${b.name}` }))} />}
              </Field>
              <Field label="Assign officer (optional)">{(id) => <SelectInput id={id} value={f.assigned_officer_id} onChange={set("assigned_officer_id")}
                placeholder="Assign later" options={officers.map((o) => ({ value: o.id, label: o.display_name }))} />}</Field>
              <Field label="Channel">{(id) => <SelectInput id={id} value={f.channel} onChange={set("channel")}
                options={Object.entries(ref.channels).map(([k, v]) => ({ value: k, label: v }))} />}</Field>
              <Field label="Source reference / complaint no." hint="Kept as the source ID; AgniDrishti also generates its own case ID.">
                {(id) => <input id={id} className="field-input" value={f.source_ref} onChange={(e) => set("source_ref")(e.target.value)} />}</Field>
              <Field label="External reference (e.g. CPGRAMS no.)">{(id) => <input id={id} className="field-input" value={f.external_ref} onChange={(e) => set("external_ref")(e.target.value)} />}</Field>
            </div>
          </Card>

          <Card title="Complainants, evidence and references" subtitle="Counts and references only; no personal data is stored">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Number of complainants">{(id) => <input id={id} type="number" min={1} className="field-input" value={f.complainant_count}
                onChange={(e) => set("complainant_count")(e.target.value)} />}</Field>
              <Field label="Complainant type">{(id) => <SelectInput id={id} value={f.complainant_type} onChange={set("complainant_type")}
                options={COMPLAINANT_TYPES.map((t) => ({ value: t, label: humanize(t) }))} />}</Field>
              <Field label="Evidence items attached">{(id) => <input id={id} type="number" min={0} className="field-input" value={f.evidence_count}
                onChange={(e) => set("evidence_count")(e.target.value)} />}</Field>
              <Field label="Evidence note" className="sm:col-span-3">{(id) => <input id={id} className="field-input" value={f.evidence_note}
                onChange={(e) => set("evidence_note")(e.target.value)} placeholder="e.g. fee receipts and bank statements (copies with PGRC)" />}</Field>
              <Field label="Court / VIP / Parliament reference">{(id) => <SelectInput id={id} value={f.reference_flag} onChange={set("reference_flag")}
                options={REFERENCE_FLAGS.map((t) => ({ value: t, label: t === "NONE" ? "None" : humanize(t) }))} />}</Field>
              <Field label="Reference details" className="sm:col-span-2">{(id) => <input id={id} className="field-input" value={f.reference_note}
                disabled={f.reference_flag === "NONE"} onChange={(e) => set("reference_note")(e.target.value)} />}</Field>
            </div>
            <div className="mt-3">
              <p className="text-xs font-semibold text-ink">Evidence / document references</p>
              {evidence.map((e, i) => (
                <div key={i} className="mt-2 grid grid-cols-[1fr_160px_auto] gap-2">
                  <input aria-label={`Evidence ${i + 1} title`} className="field-input" placeholder="Title" value={e.title}
                    onChange={(ev) => setEvidence(evidence.map((x, j) => (j === i ? { ...x, title: ev.target.value } : x)))} />
                  <input aria-label={`Evidence ${i + 1} reference`} className="field-input" placeholder="Reference no." value={e.reference_no}
                    onChange={(ev) => setEvidence(evidence.map((x, j) => (j === i ? { ...x, reference_no: ev.target.value } : x)))} />
                  <Button size="sm" variant="ghost" aria-label="Remove evidence reference" icon={<LuTrash2 aria-hidden />}
                    onClick={() => setEvidence(evidence.filter((_, j) => j !== i))} />
                </div>
              ))}
              <Button size="sm" variant="ghost" className="mt-2" icon={<LuCirclePlus aria-hidden />}
                onClick={() => setEvidence([...evidence, { title: "", reference_no: "" }])}>Add reference</Button>
            </div>
          </Card>
        </div>

        <div className="space-y-4 xl:sticky xl:top-[96px] xl:col-span-5 xl:max-h-[calc(100vh-110px)] xl:self-start xl:overflow-y-auto">
          <MatchPanel match={match} matching={matching} decision={decision} setDecision={setDecision} name={f.institution_name} />
          <PreviewPanel preview={preview} previewing={previewing} error={previewErr} ready={ready} categoryCode={f.category_code}
            onUseCategory={(code) => set("category_code")(code)} />
          <Card title="Save" tone="tint">
            {duplicates.length > 0 && (
              <label className="mb-3 flex items-start gap-2 rounded-md border border-orange/50 bg-orange-soft p-3 text-sm">
                <input type="checkbox" checked={ackDup} onChange={(e) => setAckDup(e.target.checked)} className="mt-1" />
                <span>I have checked the possible duplicate{duplicates.length > 1 ? "s" : ""} ({duplicates.map((d) => d.b).join(", ")}) and this is a separate complaint.</span>
              </label>
            )}
            {!decision && <p className="mb-2 text-sm text-orange-ink">Choose an institution match, create a new institution, or leave it unmatched for review.</p>}
            {touched && !ready && <p className="mb-2 text-sm text-red-ink">Complete the highlighted fields.</p>}
            <InlineError error={error} />
            <div className="mt-2 flex flex-wrap gap-2">
              <Button type="submit" variant="primary" busy={busy} disabled={!decision || (duplicates.length > 0 && !ackDup)}
                icon={<LuCircleCheck aria-hidden />}>Register complaint</Button>
              <Button onClick={() => { setF(blank); setEvidence([]); setDecision(null); setError(null); setTouched(false); }}>Clear form</Button>
            </div>
            <p className="mt-2 text-xs text-muted">Saving writes the case, its first timeline entry and a hash-chained audit record, then runs overlap detection.</p>
          </Card>
        </div>
      </form>
    </div>
  );
}

function MatchPanel({ match, matching, decision, setDecision, name }: { match: MatchOutcome | null; matching: boolean; decision: Decision;
  setDecision: (d: Decision) => void; name: string }) {
  return (
    <Card title={<span className="flex items-center gap-2"><LuBuilding2 aria-hidden className="text-navy" />Institution match</span>}
      subtitle="Entity resolution against the Institution Master: confirm, reject or create">
      {!match && !matching && <p className="text-sm text-muted">Type the institution name (or Permanent ID) to see candidates.</p>}
      {matching && !match && <Loading label="Matching…" className="py-3" />}
      {match && (
        <>
          <p className="mb-2 text-sm">
            <Chip tone={match.decision === "AUTO_LINK" ? "green" : match.decision === "REVIEW" ? "orange" : "neutral"}>
              {match.decision === "AUTO_LINK" ? "High-confidence match" : match.decision === "REVIEW" ? "Needs your confirmation" : "No reliable match"}
            </Chip>
            <span className="ml-2 text-xs text-muted">{match.reason}</span>
          </p>
          <ul className="space-y-2">
            {match.candidates.slice(0, 4).map((c: Candidate) => {
              const chosen = decision?.kind === "CONFIRM" && decision.institution_id === c.institution_id;
              return (
                <li key={c.institution_id} className={`rounded-md border p-2.5 ${chosen ? "border-green bg-green-soft" : "border-line"}`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <Link to={`/institutions/${c.institution_id}`} className="text-sm font-semibold">{c.name}</Link>
                      <p className="text-xs text-muted">{c.permanent_id ?? "No Permanent ID"}, {c.district ? `${c.district}, ` : ""}{c.state}</p>
                    </div>
                    <span className="flex items-center gap-2">
                      <span className={`num text-sm font-bold ${c.band === "HIGH" ? "text-green-ink" : c.band === "MEDIUM" ? "text-orange-ink" : "text-muted"}`}>{fmtPct(c.confidence)}</span>
                      {chosen ? <Button size="sm" onClick={() => setDecision({ kind: "UNMATCHED" })}>Reject</Button>
                        : <Button size="sm" variant="primary" onClick={() => setDecision({ kind: "CONFIRM", institution_id: c.institution_id, name: c.name })}>Confirm</Button>}
                    </span>
                  </div>
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {c.factors.slice(0, 4).map((x) => <li key={x.factor} className="max-w-full"><Chip wrap tone={x.effect === "-" ? "red" : "neutral"}>{x.label}</Chip></li>)}
                  </ul>
                </li>
              );
            })}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
            <Button size="sm" variant={decision?.kind === "CREATE" ? "primary" : "secondary"} onClick={() => setDecision({ kind: "CREATE" })}>
              Not listed: create “{name.trim().slice(0, 40) || "new institution"}”</Button>
            <Button size="sm" variant={decision?.kind === "UNMATCHED" ? "primary" : "secondary"} onClick={() => setDecision({ kind: "UNMATCHED" })}>
              Leave unmatched for review</Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            Selected: {decision?.kind === "CONFIRM" ? <strong className="text-green-ink">{decision.name}</strong>
              : decision?.kind === "CREATE" ? "a new Institution Master record (state required)"
              : decision?.kind === "UNMATCHED" ? "no institution; the case goes to the match-review queue" : "nothing yet"}.
            {" "}{match.note}
          </p>
        </>
      )}
    </Card>
  );
}

function PreviewPanel({ preview, previewing, error, ready, categoryCode, onUseCategory }: { preview: IntakePreview | null; previewing: boolean;
  error: ApiError | null; ready: boolean; categoryCode: string; onUseCategory: (c: string) => void }) {
  const ref = useRefData();
  if (!ready) {
    return <Card title="Priority, SLA and overlap check"><p className="text-sm text-muted">Complete the required fields to see the priority estimate and any duplicate or conflicting cases.</p></Card>;
  }
  if (!preview) return <Card title="Priority, SLA and overlap check">{error ? <InlineError error={error} /> : <Loading label="Checking…" className="py-3" />}</Card>;
  const top = (preview.ml_suggestion.top as Array<{ category: string; probability: number }>) ?? [];
  const overlaps = preview.potential_overlaps as unknown as PairSignal[];
  const open = preview.open_cases_at_institution as unknown as OpenCaseBrief[];
  return (
    <Card title={<span className="flex items-center gap-2">Priority estimate <BandChip band={preview.priority.band} score={preview.priority.score} /></span>}
      subtitle={`SLA ${String(preview.sla.sla_days)} days: due ${fmtDate(String(preview.sla.due_date))}`}
      actions={previewing && <span className="text-xs text-muted">updating…</span>}>
      <ul className="flex flex-wrap gap-1.5">
        {preview.priority.chips.filter((c) => c.kind !== "ml").map((c) => (
          <li key={c.key} className="max-w-full"><Chip wrap tone={c.kind === "keyword" ? "red" : c.points > 0 ? "blue" : "neutral"} title={c.detail ?? undefined}>
            {c.label}{c.points ? ` +${c.points.toFixed(1)}` : ""}</Chip></li>
        ))}
      </ul>
      {top.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <LuSparkles aria-hidden className="text-navy" />
          Text model suggests <strong>{ref.categoryLabel(top[0].category)}</strong> ({fmtPct(top[0].probability)})
          {top[0].category !== categoryCode && <Button size="sm" variant="ghost" onClick={() => onUseCategory(top[0].category)}>Use this category</Button>}
          <span className="block w-full text-xs text-muted">{String(preview.ml_suggestion.label)}</span>
        </p>
      )}
      <div className="mt-3 border-t border-line pt-3">
        <p className="text-sm font-semibold text-ink">Duplicates and conflicts across Bureaus/Cells</p>
        {!preview.selected_institution && <p className="text-sm text-muted">No institution selected yet: overlap checks run once the institution is confirmed.</p>}
        {preview.selected_institution && overlaps.length === 0 && !preview.duplicate_warning && (
          <p className="text-sm text-green-ink">No duplicate, related or conflicting case found at {String(preview.selected_institution.name)}.</p>
        )}
        <ul className="mt-1 space-y-2">
          {[...overlaps, ...(preview.duplicates as unknown as PairSignal[]).filter((d) => d.rules?.[0]?.code === "SRC")].map((o, i) => (
            <li key={`${o.b}-${i}`} className={`rounded-md border p-2 text-sm ${o.tier === "CONFLICT" ? "border-red/50 bg-red-soft" : o.tier === "DUPLICATE" ? "border-orange/50 bg-orange-soft" : "border-line"}`}>
              <p className="flex flex-wrap items-center gap-2"><TierChip tier={o.tier} /><Link to={`/cases/${o.b}`} className="font-semibold">{o.b}</Link>
                {o.tier === "DUPLICATE" && <LuTriangleAlert aria-hidden className="text-orange-ink" />}</p>
              {o.rules.map((r) => <p key={r.code} className="mt-0.5 text-xs text-ink">{r.text}</p>)}
            </li>
          ))}
        </ul>
        {open.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold text-ink">Open cases already at this institution</p>
            <ul className="mt-1 space-y-1 text-xs">
              {open.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center gap-2"><Link to={`/cases/${o.id}`}>{o.id}</Link><BureauTag code={o.bureau_code} />
                  <span className="text-muted">{ref.categoryLabel(o.category_code)}, {humanize(o.status)}</span></li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function Created({ created, onAnother }: { created: CreatedCase; onAnother: () => void }) {
  return (
    <div className="mx-auto max-w-2xl">
      <Card title="Complaint registered" tone="tint">
        <p className="flex items-center gap-2 text-lg"><LuCircleCheck aria-hidden className="text-green" />
          <Link to={`/cases/${created.case_id}`} className="font-bold">{created.case_id}</Link> has been saved.</p>
        <p className="mt-1 text-sm text-muted">Institution: {created.institution_id ? <Link to={`/institutions/${created.institution_id}`}>{created.institution_id}</Link> : "not linked yet"} ({humanize(created.match_status)}).</p>
        {created.overlap_alerts.length > 0 ? (
          <div className="mt-3 rounded-md border border-red/50 bg-red-soft p-3">
            <p className="font-semibold text-red-ink">Overlap detection raised {created.overlap_alerts.length} alert(s):</p>
            <ul className="mt-1 space-y-1 text-sm">
              {created.overlap_alerts.map((a) => <li key={a.alert_id} className="flex items-center gap-2"><TierChip tier={a.tier} />
                <Link to={`/overlaps/${a.alert_id}`}>{a.alert_id}</Link> <span className="text-xs text-muted">{a.cases.join(", ")}</span></li>)}
            </ul>
          </div>
        ) : <p className="mt-3 text-sm text-green-ink">No overlap with other open cases was found.</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          <LinkButton to={`/cases/${created.case_id}`} variant="primary">Open the case</LinkButton>
          <Button onClick={onAnother}>Register another</Button>
        </div>
      </Card>
    </div>
  );
}

