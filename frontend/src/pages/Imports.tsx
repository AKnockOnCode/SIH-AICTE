import { useState, type DragEvent } from "react";
import { LuCircleCheck, LuDownload, LuFileSpreadsheet, LuFileUp, LuTriangleAlert } from "react-icons/lu";
import { api } from "../api/client";
import type { CommitOut, DictionaryOut, IssuePage, JobList, JobOut, UploadOut, ValidateOut } from "../api/models";
import { useTitle } from "../components/layout";
import {
  Button, Card, Chip, Disclosure, Empty, ErrorState, InlineError, Loading, PageHeader, Pagination, SelectInput, Tabs,
} from "../components/ui";
import { fmtDateTime, fmtNum, humanize, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";

type Kind = "INSTITUTIONS" | "COMPLAINTS" | "PUBLIC_SIGNALS";
const KIND_LABEL: Record<Kind, string> = { INSTITUTIONS: "Institutions", COMPLAINTS: "Complaints / cases", PUBLIC_SIGNALS: "Public signals" };
interface FieldSpec {
  key: string;
  label: string;
  required: boolean;
  type: string;
  description?: string;
}

export function ImportsPage() {
  useTitle("Data Import & Mapping");
  const { can, bump, reloadReference } = useSession();
  const toast = useToast();
  const [tab, setTab] = useState<"wizard" | "history" | "dictionary">("wizard");
  const [kind, setKind] = useState<Kind>("COMPLAINTS");
  const [upload, setUpload] = useState<UploadOut | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [validation, setValidation] = useState<ValidateOut | null>(null);
  const [ack, setAck] = useState(false);
  const [committed, setCommitted] = useState<CommitOut | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const step = useAction();
  const canRun = can("import.run");
  const canSignals = can("signals.import");

  const reset = () => {
    setUpload(null);
    setMapping({});
    setValidation(null);
    setAck(false);
    setCommitted(null);
    step.setError(null);
  };
  const loaded = (u: UploadOut) => {
    setUpload(u);
    setMapping({ ...u.suggested_mapping });
    setValidation(null);
    setCommitted(null);
    setAck(false);
  };
  const sendFile = async (file: File) => {
    const form = new FormData();
    form.set("file", file);
    const out = await step.run(() => api.upload<UploadOut>("/api/imports/upload", form, { kind }));
    if (out) loaded(out);
  };
  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void sendFile(f);
  };
  const template = async (k: Kind, fmt: "csv" | "xlsx") => {
    try {
      await api.download("/api/imports/template", { kind: k, fmt }, `agnidrishti-${k.toLowerCase()}-template.${fmt}`);
    } catch (e) {
      toast.push((e as Error).message, "error");
    }
  };

  const fields = (upload?.fields ?? []) as unknown as FieldSpec[];
  const missingRequired = fields.filter((f) => f.required && !mapping[f.key]);
  return (
    <div>
      <PageHeader title="Data import and column mapping"
        subtitle="Import institutions, complaints or public signals from CSV or Excel. Map your columns, run a dry run with row-level checks, then commit in one transaction."
        actions={<>
          {(["INSTITUTIONS", "COMPLAINTS", "PUBLIC_SIGNALS"] as Kind[]).map((k) => (
            <Button key={k} size="sm" variant="ghost" icon={<LuDownload aria-hidden />} onClick={() => template(k, "csv")}>{KIND_LABEL[k]} template</Button>
          ))}
        </>} />
      <Tabs value={tab} onChange={setTab} className="mb-4" tabs={[{ value: "wizard", label: "Import wizard" }, { value: "history", label: "Import history and provenance" },
        { value: "dictionary", label: "Data dictionary" }]} />
      {tab === "history" && <History onOpen={async (id) => {
        const out = await step.run(() => api.get<UploadOut>(`/api/imports/${id}`));
        if (out) {
          setKind(out.job.kind as Kind);
          loaded(out);
          if (out.job.summary) setCommitted({ job: out.job, summary: out.job.summary });
          setTab("wizard");
        }
      }} />}
      {tab === "dictionary" && <Dictionary onTemplate={template} />}
      {tab === "wizard" && (
        <div className="space-y-4">
          {!canRun && <p className="rounded-md border border-line bg-tint px-3 py-2 text-sm text-muted">Your demo role can view import history and the data dictionary but cannot run imports.</p>}
          <InlineError error={step.error} />
          <Card title="1. Choose the data type and file">
            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-col text-xs font-semibold text-ink">Data type
                <SelectInput className="mt-1 w-56 font-normal" value={kind} disabled={!!upload} onChange={(v) => setKind(v as Kind)}
                  options={(["COMPLAINTS", "INSTITUTIONS", "PUBLIC_SIGNALS"] as Kind[]).filter((k) => k !== "PUBLIC_SIGNALS" || canSignals)
                    .map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
              </label>
              {!upload ? (
                <label onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={onDrop}
                  className={`flex min-w-72 flex-1 cursor-pointer items-center gap-3 rounded-md border-2 border-dashed px-4 py-4 text-sm ${dragOver ? "border-blue bg-blue-soft" : "border-line-strong bg-white"}`}>
                  <LuFileUp aria-hidden className="text-2xl text-blue" />
                  <span><strong>Choose a CSV or Excel file</strong> or drop it here. Up to 10 MB; first row must hold the column names.</span>
                  <input type="file" accept=".csv,.xlsx" className="sr-only" disabled={!canRun || step.busy} onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void sendFile(f);
                    e.target.value = "";
                  }} />
                </label>
              ) : (
                <div className="flex flex-1 flex-wrap items-center gap-3 text-sm">
                  <LuFileSpreadsheet aria-hidden className="text-2xl text-green" />
                  <span><strong>{upload.job.file_name}</strong> ({fmtNum(upload.job.size_bytes)} bytes, {upload.job.id})
                    <span className="block text-xs text-muted">Uploaded {fmtDateTime(upload.job.created_at)} by {upload.job.uploaded_by} ({roleLabel(upload.job.uploaded_role)}).
                      SHA-256 {upload.job.file_sha256.slice(0, 16)}…</span></span>
                  <Button size="sm" onClick={reset}>Start over</Button>
                </div>
              )}
            </div>
            {kind === "PUBLIC_SIGNALS" && <p className="mt-3 text-xs text-muted">Public signals are stored separately from complaints and never create or change a case. Record only real, checkable source URLs with your own short summary.</p>}
            {step.busy && <Loading label="Working…" className="py-2" />}
          </Card>

          {upload && upload.sheets.length > 1 && (
            <Card title="2. Choose the sheet" subtitle={`This workbook has ${upload.sheets.length} sheets`}>
              <div className="flex flex-wrap gap-2">
                {upload.sheets.map((s) => (
                  <Button key={s} size="sm" variant={s === upload.sheet ? "primary" : "secondary"} disabled={committed !== null} onClick={async () => {
                    const out = await step.run(() => api.post<UploadOut>(`/api/imports/${upload.job.id}/sheet`, { sheet: s }));
                    if (out) loaded(out);
                  }}>{s}</Button>
                ))}
              </div>
              {upload.row_count === 0 && <p className="mt-2 text-sm text-orange-ink">The selected sheet has no data rows. Choose another sheet.</p>}
            </Card>
          )}

          {upload && upload.row_count > 0 && (
            <Card title={`${upload.sheets.length > 1 ? "3" : "2"}. Map your columns`} subtitle={`${fmtNum(upload.row_count)} data rows found${upload.sheet && upload.sheet !== "(csv)" ? ` in “${upload.sheet}”` : ""}. Suggested matches are pre-filled from column names.`}>
              <div className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">
                {fields.map((f) => (
                  <div key={f.key} className="grid grid-cols-[minmax(150px,1fr)_minmax(160px,1fr)] items-center gap-2">
                    <span className="text-sm" title={f.description}>{f.label}{f.required && <span className="text-red-ink"> *</span>}
                      <span className="block text-xs text-muted">{f.type}</span></span>
                    <SelectInput aria-label={`Source column for ${f.label}`} value={mapping[f.key] ?? ""} placeholder="Not in file" disabled={committed !== null}
                      invalid={f.required && !mapping[f.key]}
                      onChange={(v) => { setMapping({ ...mapping, [f.key]: v }); setValidation(null); }}
                      options={upload.columns.map((c) => ({ value: c, label: c }))} />
                  </div>
                ))}
              </div>
              <Disclosure summary={`Preview of the first ${upload.preview.length} rows`}>
                <div className="max-h-72 overflow-auto">
                  <table className="data-table">
                    <thead><tr>{upload.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
                    <tbody>{upload.preview.map((r, i) => <tr key={i}>{upload.columns.map((c) => <td key={c} className="max-w-56 truncate">{r[c]}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </Disclosure>
              {committed === null && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button variant="primary" busy={step.busy} disabled={!canRun || missingRequired.length > 0} onClick={async () => {
                    const out = await step.run(() => api.post<ValidateOut>(`/api/imports/${upload.job.id}/validate`, { mapping }));
                    if (out) setValidation(out);
                  }}>Run dry run (validate, nothing is saved)</Button>
                  {missingRequired.length > 0 && <span className="text-sm text-red-ink">Map the required fields: {missingRequired.map((f) => f.label).join(", ")}.</span>}
                </div>
              )}
            </Card>
          )}

          {validation && <ValidationCard v={validation} />}

          {validation && !committed && (
            <Card title="Commit" tone="tint">
              {validation.counts.invalid > 0 && (
                <label className="mb-3 flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span>Import the {fmtNum(validation.counts.valid)} valid rows and skip the {fmtNum(validation.counts.invalid)} invalid row(s) listed above. Skipped rows are recorded in the import summary.</span>
                </label>
              )}
              <Button variant="primary" busy={step.busy} icon={<LuCircleCheck aria-hidden />} disabled={!canRun || (validation.counts.invalid > 0 && !ack) || validation.counts.valid === 0}
                onClick={async () => {
                  const out = await step.run(() => api.post<CommitOut>(`/api/imports/${validation.job.id}/commit`, { mapping_hash: validation.mapping_hash, acknowledge_skipped: ack }));
                  if (out) {
                    setCommitted(out);
                    bump();
                    reloadReference();
                    toast.push(`Import ${out.job.id} committed.`);
                  }
                }}>Commit import</Button>
              <p className="mt-2 text-xs text-muted">One database transaction: if anything unexpected fails, nothing is imported. The mapping and decision are written to the audit trail.</p>
            </Card>
          )}
          {committed && <Summary c={committed} />}
        </div>
      )}
    </div>
  );
}

function ValidationCard({ v }: { v: ValidateOut }) {
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState("");
  const issues = useApi<IssuePage>(`/api/imports/${v.job.id}/issues`, { page, page_size: 25, severity: severity || undefined });
  const c = v.counts;
  const tiles: Array<[string, number, string]> = [
    ["Rows", c.total, "text-navy-ink"], ["Valid", c.valid, "text-green-ink"], ["Invalid (will be skipped)", c.invalid, c.invalid ? "text-red-ink" : "text-ink"],
    ["With warnings", c.with_warnings ?? 0, "text-orange-ink"], ["New records", (c.insert ?? 0) + (c.insert_needs_review ?? 0), "text-blue-ink"],
    ["Updates", c.update ?? 0, "text-ink"], ["Matched existing", c.matched ?? 0, "text-ink"], ["Need match review", (c.review ?? 0) + (c.insert_needs_review ?? 0), "text-orange-ink"],
  ];
  return (
    <Card title="Dry-run result" subtitle={`Validated ${fmtDateTime(v.job.validated_at)} with mapping ${v.mapping_hash}. Nothing has been saved yet.`}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {tiles.map(([label, n, cls]) => (
          <div key={label} className="rounded-md border border-line px-3 py-2"><span className={`num block text-xl font-bold ${cls}`}>{fmtNum(n)}</span><span className="text-xs text-muted">{label}</span></div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-ink">Row-level issues</p>
            <SelectInput aria-label="Issue severity" className="w-40" value={severity} onChange={(s) => { setSeverity(s); setPage(1); }} placeholder="Errors and warnings"
              options={[{ value: "ERROR", label: "Errors only" }, { value: "WARNING", label: "Warnings only" }]} />
          </div>
          {issues.data && issues.data.total === 0 ? <p className="text-sm text-green-ink">No issues.</p> : (
            <div className="max-h-96 overflow-auto">
              <table className="data-table">
                <thead><tr><th scope="col" className="num">Row</th><th scope="col">Field</th><th scope="col">Issue</th><th scope="col">Value</th></tr></thead>
                <tbody>
                  {(issues.data?.items ?? []).map((i, k) => (
                    <tr key={k}>
                      <td className="num">{String(i.row_number)}</td>
                      <td className="text-xs">{String(i.field ?? "—")}</td>
                      <td><span className="flex items-start gap-1.5">{i.severity === "ERROR" ? <LuTriangleAlert aria-hidden className="mt-0.5 shrink-0 text-red-ink" /> : <LuTriangleAlert aria-hidden className="mt-0.5 shrink-0 text-orange" />}
                        <span><span className={i.severity === "ERROR" ? "font-semibold text-red-ink" : "font-semibold text-orange-ink"}>{humanize(String(i.code))}</span>: {String(i.message)}</span></span></td>
                      <td className="max-w-40 truncate text-xs" title={String(i.value ?? "")}>{String(i.value ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {issues.data && issues.data.total > 25 && <Pagination page={page} pageSize={25} total={issues.data.total} onPage={setPage} />}
        </div>
        <div>
          <p className="mb-2 text-sm font-semibold text-ink">What will happen to each row</p>
          <div className="max-h-96 overflow-auto">
            <table className="data-table">
              <thead><tr><th scope="col" className="num">Row</th><th scope="col">Outcome</th><th scope="col">Notes</th></tr></thead>
              <tbody>
                {v.rows.map((r) => (
                  <tr key={String(r.row_number)}>
                    <td className="num">{String(r.row_number)}</td>
                    <td><Chip tone={r.outcome === "SKIP" ? "red" : String(r.outcome).includes("REVIEW") ? "orange" : "green"}>{humanize(String(r.outcome))}</Chip></td>
                    <td className="text-xs">{String(r.notes ?? "")}{r.institution_id ? <> (<Link to={`/institutions/${String(r.institution_id)}`}>{String(r.institution_id)}</Link>)</> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Summary({ c }: { c: CommitOut }) {
  const s = c.summary as { counts?: Record<string, number>; total_rows?: number; committed_at?: string; committed_by?: string; policy?: string;
    results?: Array<{ row: number; outcome: string; entity_id: string | null; notes: string | null }>; error?: string };
  return (
    <Card title={`Import ${c.job.id}: ${humanize(c.job.status)}`} tone="tint"
      subtitle={s.committed_at ? `Committed ${fmtDateTime(s.committed_at)} by ${s.committed_by}. Policy: ${s.policy}.` : s.error}>
      {s.counts && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
          {Object.entries(s.counts).map(([k, n]) => (
            <div key={k} className="rounded-md border border-line bg-white px-3 py-2"><span className="num block text-xl font-bold text-navy-ink">{fmtNum(n)}</span>
              <span className="text-xs text-muted">{humanize(k)}</span></div>
          ))}
        </div>
      )}
      {s.results && (
        <Disclosure summary={`Row results (${s.results.length})`}>
          <ul className="max-h-72 space-y-0.5 overflow-auto text-xs">
            {s.results.map((r) => (
              <li key={r.row}>Row {r.row}: {humanize(r.outcome)}{r.entity_id && <> → <Link to={r.entity_id.startsWith("INS-") ? `/institutions/${r.entity_id}` : r.entity_id.startsWith("SIG-") ? "/signals" : `/cases/${r.entity_id}`}>{r.entity_id}</Link></>}
                {r.notes ? <span className="text-muted">. {r.notes}</span> : null}</li>
            ))}
          </ul>
        </Disclosure>
      )}
      <p className="mt-2 text-sm"><Link to={c.job.kind === "PUBLIC_SIGNALS" ? "/signals" : c.job.kind === "INSTITUTIONS" ? "/institutions" : "/search?sort=received_desc"}>
        View the imported records</Link>. Rows that need an institution match are in <Link to="/match-reviews">Match review</Link>.</p>
    </Card>
  );
}

function History({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, error, loading, reload } = useApi<JobList>("/api/imports");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  if (data.items.length === 0) return <Empty title="No imports yet">Use the import wizard to load a CSV or Excel file. The sample files in backend/data/samples include deliberate errors.</Empty>;
  return (
    <Card title="Import provenance" subtitle="Every upload with its file checksum, sheet, mapping, uploader and outcome">
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead><tr><th scope="col">Job</th><th scope="col">Type</th><th scope="col">File / sheet</th><th scope="col" className="num">Rows</th>
            <th scope="col">Status</th><th scope="col">Uploaded</th><th scope="col">Result</th></tr></thead>
          <tbody>
            {data.items.map((j: JobOut) => {
              const counts = (j.summary as { counts?: Record<string, number> } | null)?.counts;
              return (
                <tr key={j.id}>
                  <td><button type="button" className="font-semibold text-blue-ink hover:underline" onClick={() => onOpen(j.id)}>{j.id}</button></td>
                  <td>{KIND_LABEL[j.kind as Kind] ?? j.kind}</td>
                  <td>{j.file_name}{j.sheet_name && <span className="block text-xs text-muted">sheet “{j.sheet_name}”, SHA-256 {j.file_sha256.slice(0, 12)}…</span>}</td>
                  <td className="num">{fmtNum(j.row_count)}</td>
                  <td><Chip tone={j.status === "COMMITTED" ? "green" : j.status === "FAILED" ? "red" : "blue"}>{humanize(j.status)}</Chip></td>
                  <td className="text-xs">{fmtDateTime(j.created_at)}<span className="block text-muted">{j.uploaded_by} ({roleLabel(j.uploaded_role)})</span></td>
                  <td className="text-xs">{counts ? Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `${humanize(k)} ${n}`).join(", ") : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Dictionary({ onTemplate }: { onTemplate: (k: Kind, fmt: "csv" | "xlsx") => void }) {
  const { data, error, loading, reload } = useApi<DictionaryOut>("/api/imports/dictionary");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  return (
    <div className="space-y-4">
      <Card title="Import policy" tone="tint"><p className="text-sm">{data.policy}</p></Card>
      {(Object.entries(data.fields) as Array<[Kind, Array<Record<string, unknown>>]>).map(([k, fields]) => (
        <Card key={k} title={KIND_LABEL[k] ?? k} actions={<>
          <Button size="sm" icon={<LuDownload aria-hidden />} onClick={() => onTemplate(k, "csv")}>CSV template</Button>
          <Button size="sm" icon={<LuFileSpreadsheet aria-hidden />} onClick={() => onTemplate(k, "xlsx")}>Excel template</Button>
        </>}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th scope="col">Field</th><th scope="col">Required</th><th scope="col">Type</th><th scope="col">Recognised column names</th><th scope="col">Notes</th></tr></thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={String(f.key)}>
                    <td><span className="font-semibold">{String(f.label)}</span><span className="block font-mono text-xs text-muted">{String(f.key)}</span></td>
                    <td>{f.required ? <Chip tone="red">Required</Chip> : "Optional"}</td>
                    <td className="text-xs">{String(f.type)}</td>
                    <td className="text-xs">{(f.synonyms as string[] | undefined)?.join(", ")}</td>
                    <td className="text-xs">{String(f.description ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
      <Card title="Accepted values"><pre className="max-h-80 overflow-auto rounded bg-tint p-3 text-xs">{JSON.stringify(data.accepted_values, null, 2)}</pre></Card>
    </div>
  );
}
