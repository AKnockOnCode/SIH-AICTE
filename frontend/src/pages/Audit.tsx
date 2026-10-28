import { Fragment, useState } from "react";
import { LuCircleCheck, LuCircleX, LuShieldCheck } from "react-icons/lu";
import { api } from "../api/client";
import type { AuditPage as AuditPageT, AuditRow, PermRow, StatusOut, VerifyOut } from "../api/models";
import { UrlTextInput } from "../components/cases";
import { useTitle } from "../components/layout";
import { Button, Card, Chip, ErrorState, InlineError, KeyValues, Loading, MultiSelect, PageHeader, Pagination, SelectInput, Tabs } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct, humanize, shortHash, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useRefData, useSession } from "../lib/session";

const ROLES = ["COMPETENT_AUTHORITY", "RB_OFFICER", "PGRC_OFFICER", "REGIONAL_OFFICE", "SENIOR_MANAGEMENT", "SYSTEM"];

function entityLink(type: string, id: string | null) {
  if (!id) return "—";
  const to = type === "case" ? `/cases/${id}` : type === "institution" ? `/institutions/${id}` : type === "overlap_alert" ? `/overlaps/${id}`
    : type === "master_case" ? `/master-cases/${id}` : type === "match_review" ? `/match-reviews?focus=${id}` : type === "import_job" ? "/imports"
    : type === "alert" ? `/alerts?q=${id}&state=NEW,ACKNOWLEDGED,RESOLVED,DISMISSED` : null;
  return to ? <Link to={to}>{id}</Link> : id;
}

export function AuditPage() {
  useTitle("Audit Trail & System Status");
  const { params } = useLocation();
  const tab = params.get("tab") ?? "audit";
  return (
    <div>
      <PageHeader title="Audit trail and system status"
        subtitle="Every meaningful action is recorded in a hash-chained log. Verification recomputes every hash from the first event." />
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t === "audit" ? null : t, page: null })} className="mb-4" tabs={[
        { value: "audit", label: "Audit trail" }, { value: "status", label: "System status" }, { value: "permissions", label: "Roles and permissions" }]} />
      {tab === "audit" && <AuditTrail />}
      {tab === "status" && <SystemStatus />}
      {tab === "permissions" && <Permissions />}
    </div>
  );
}

function AuditTrail() {
  const { params } = useLocation();
  const ref = useRefData();
  const { can } = useSession();
  const page = Number(params.get("page") ?? "1") || 1;
  const query = {
    page, page_size: 30, date_from: params.get("date_from") || undefined, date_to: params.get("date_to") || undefined,
    actor: params.get("actor") || undefined, role: listParam(params, "role"), action: params.get("action") || undefined,
    entity_id: params.get("entity_id") || undefined, bureau: params.get("bureau") || undefined,
  };
  const { data, error, loading, reload } = useApi<AuditPageT>("/api/audit", query);
  const [open, setOpen] = useState<number | null>(null);
  const verify = useAction();
  const [result, setResult] = useState<VerifyOut | null>(null);
  return (
    <div className="space-y-4">
      <Card title="Verify the hash chain" tone="tint"
        actions={can("audit.verify") && <Button variant="primary" icon={<LuShieldCheck aria-hidden />} busy={verify.busy} onClick={async () => {
          const out = await verify.run(() => api.post<VerifyOut>("/api/audit/verify"));
          if (out) setResult(out);
        }}>Verify now</Button>}>
        {result ? (
          <p className={`flex items-start gap-2 text-sm ${result.ok ? "text-green-ink" : "text-red-ink"}`}>
            {result.ok ? <LuCircleCheck aria-hidden className="mt-0.5 shrink-0" /> : <LuCircleX aria-hidden className="mt-0.5 shrink-0" />}
            <span>{result.ok ? `Chain intact: ${fmtNum(result.checked)} events verified. Head hash ${shortHash(result.head_hash, 16)}.`
              : `Chain broken at event #${result.first_bad_seq}: ${result.reason}. Last good event #${result.last_good_seq}.`}</span>
          </p>
        ) : <p className="text-sm text-muted">{data?.note ?? "Recompute every event hash and link."}</p>}
        <InlineError error={verify.error} />
      </Card>
      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
        <label className="flex flex-col text-xs font-semibold text-ink">From<input type="date" className="field-input mt-1 w-40 font-normal" value={params.get("date_from") ?? ""}
          onChange={(e) => setQuery({ date_from: e.target.value, page: null })} /></label>
        <label className="flex flex-col text-xs font-semibold text-ink">To<input type="date" className="field-input mt-1 w-40 font-normal" value={params.get("date_to") ?? ""}
          onChange={(e) => setQuery({ date_to: e.target.value, page: null })} /></label>
        <UrlTextInput param="actor" label="Actor" placeholder="e.g. pgrc.officer" className="w-44" />
        <MultiSelect label="Role" className="w-full sm:w-52" value={listParam(params, "role")} onChange={(v) => setQuery({ role: v, page: null })}
          options={ROLES.map((r) => ({ value: r, label: roleLabel(r) }))} />
        <label className="flex flex-col text-xs font-semibold text-ink">Action
          <SelectInput className="mt-1 w-56 font-normal" value={params.get("action") ?? ""} onChange={(v) => setQuery({ action: v || null, page: null })} placeholder="Any"
            options={(data?.actions ?? []).map((a) => ({ value: a, label: humanize(a) }))} /></label>
        <UrlTextInput param="entity_id" label="Entity ID" placeholder="e.g. PGRC-5530" className="w-40" />
        <label className="flex flex-col text-xs font-semibold text-ink">Bureau/Cell
          <SelectInput className="mt-1 w-32 font-normal" value={params.get("bureau") ?? ""} onChange={(v) => setQuery({ bureau: v || null, page: null })} placeholder="Any"
            options={ref.bureaus.map((b) => ({ value: b.code, label: b.code }))} /></label>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && (
        <Card title={`${fmtNum(data.total)} audit event${data.total === 1 ? "" : "s"}`} subtitle="Newest first. Expand an event to see before/after values and hashes.">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th scope="col" className="num">#</th><th scope="col">Time</th><th scope="col">Actor</th><th scope="col">Action</th>
                <th scope="col">Entity</th><th scope="col">Remarks</th><th scope="col">Hash (prev → this)</th></tr></thead>
              <tbody>
                {data.items.map((e: AuditRow) => (
                  <Fragment key={e.seq}>
                    <tr className="cursor-pointer" onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                      <td className="num">{e.seq}</td>
                      <td className="text-xs whitespace-nowrap">{fmtDateTime(e.ts)}</td>
                      <td className="text-xs">{e.actor_label ?? e.actor_id}<span className="block text-muted">{roleLabel(e.actor_role)}{e.actor_bureau ? `, ${e.actor_bureau}` : ""}</span></td>
                      <td><Chip tone={e.action === "ACCESS_DENIED" ? "red" : e.action.includes("CONFLICT") || e.action.startsWith("OVERLAP") ? "orange" : "neutral"}>{humanize(e.action)}</Chip></td>
                      <td className="text-xs">{humanize(e.entity_type)}<span className="block">{entityLink(e.entity_type, e.entity_id)}</span></td>
                      <td className="max-w-72 text-xs">{e.remarks ?? "—"}</td>
                      <td className="font-mono text-[11px] text-muted">{shortHash(e.prev_hash, 8)} → <span className="text-ink">{shortHash(e.hash, 8)}</span></td>
                    </tr>
                    {open === e.seq && (
                      <tr>
                        <td colSpan={7} className="bg-tint">
                          <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-2">
                            <div><p className="font-semibold">Before</p><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{e.before_json ? JSON.stringify(JSON.parse(e.before_json), null, 1) : "—"}</pre></div>
                            <div><p className="font-semibold">After</p><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{e.after_json ? JSON.stringify(JSON.parse(e.after_json), null, 1) : "—"}</pre></div>
                            <p className="font-mono break-all md:col-span-2">event {e.event_id}<br />payload {e.payload_hash}<br />previous {e.prev_hash}<br />this {e.hash}</p>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={30} total={data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />
        </Card>
      )}
    </div>
  );
}

function SystemStatus() {
  const { data, error, loading, reload } = useApi<StatusOut>("/api/system/status");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  const app = data.app as Record<string, string | boolean>;
  const d = data.data as { mode: string; counts: Record<string, number>; non_synthetic_cases: number; seed: Record<string, string | number> | null };
  const m = data.models as Record<string, Record<string, unknown>>;
  const llm = data.llm as { configured: boolean; model: string | null; used_for: string[]; note: string };
  const audit = data.audit as Record<string, string | number>;
  const imports = data.imports as { last: Record<string, unknown> | null };
  const cls = m.classifier ?? {};
  const mat = m.matcher ?? {};
  const br = m.breach ?? {};
  const matMetrics = (mat.metrics ?? {}) as Record<string, unknown>;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Card title="Application" tone="tint">
        <KeyValues items={[["Version", String(app.version)], ["Today (as used for SLA)", `${app.today}${app.date_frozen ? " (frozen for the demo)" : ""}`],
          ["Database", String(app.database)], ["API", String(app.api_framework)], ["Network needed at runtime", app.offline ? "No (works offline)" : "Yes"]]} />
      </Card>
      <Card title="Data mode">
        <p className="mb-2"><Chip tone={d.mode === "SYNTHETIC" ? "neutral" : "blue"}>{d.mode === "SYNTHETIC" ? "Synthetic demo data only" : humanize(d.mode)}</Chip>
          <span className="ml-2 text-sm text-muted">{fmtNum(d.non_synthetic_cases)} entered or imported case(s)</span></p>
        <KeyValues cols={3} items={Object.entries(d.counts).map(([k, v]) => [humanize(k), fmtNum(v)])} />
        {d.seed && <p className="mt-2 text-xs text-muted">Seed {String(d.seed.seed)}, anchor {String(d.seed.anchor_date)}, generator {String(d.seed.generator_version)}, seeded {fmtDateTime(String(d.seed.created_at))}. Fingerprint {String(d.seed.fingerprint).slice(0, 16)}…</p>}
      </Card>
      <Card title="Local models">
        <KeyValues cols={1} items={[
          ["Category classifier", `${cls.available ? "Available" : "Not trained"}: TF-IDF + logistic regression, ${String(cls.n_examples ?? "?")} synthetic examples, macro F1 ${String(cls.macro_f1 ?? "—")} on held-out synthetic texts. ${String(cls.caveat ?? "")}`],
          ["Institution matcher", `${mat.available ? "Available" : "Not trained"}: Brier ${String(matMetrics.brier_score ?? "—")}, accuracy ${matMetrics.accuracy_at_0_5 !== undefined ? fmtPct(Number(matMetrics.accuracy_at_0_5), 1) : "—"} on ${fmtNum(Number(matMetrics.n_pairs ?? 0))} pairs (${String(matMetrics.validation ?? "")}).`],
          ["SLA breach model", `${br.status ? humanize(String(br.status)) : "—"}: ${String(br.method ?? "")}. C-index ${String(br.c_index ?? "—")}.`],
          ["Risk index", String((m.risk as Record<string, string> | undefined)?.method ?? "—")],
          ["Forecast", String((m.forecast as Record<string, string> | undefined)?.method ?? "—")],
        ]} />
      </Card>
      <Card title="Optional AI wording (Anthropic API)">
        <p className="text-sm"><Chip tone={llm.configured ? "green" : "neutral"}>{llm.configured ? `Configured (${llm.model})` : "Not configured"}</Chip></p>
        <p className="mt-2 text-sm text-ink">Used only for: {llm.used_for.join("; ")}.</p>
        <p className="mt-1 text-xs text-muted">{llm.note}</p>
      </Card>
      <Card title="Audit log">
        <KeyValues items={[["Events", fmtNum(Number(audit.events))], ["Head event", `#${audit.head_seq}`], ["Head hash", shortHash(String(audit.head_hash), 20)],
          ["Last event", fmtDateTime(String(audit.last_event_at))]]} />
      </Card>
      <Card title="Last import">
        {imports.last ? <KeyValues items={[["Job", String(imports.last.id)], ["File", String(imports.last.file_name)], ["Status", humanize(String(imports.last.status))],
          ["When", fmtDateTime(String(imports.last.created_at))]]} /> : <p className="text-sm text-muted">No import has been run.</p>}
      </Card>
      <p className="text-xs text-muted xl:col-span-2">{data.disclaimer}</p>
    </div>
  );
}

function Permissions() {
  const { data, error, loading, reload } = useApi<PermRow[]>("/api/system/permissions");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  const roles = Object.keys(data[0]?.roles ?? {});
  return (
    <Card title="Permission matrix (enforced by the server on every request)"
      subtitle="Object-level rules also apply: officers act only on their own Bureau/Cell’s cases, the Regional Office only within its region.">
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead><tr><th scope="col">Permission</th>{roles.map((r) => <th key={r} scope="col" className="text-center">{roleLabel(r)}</th>)}</tr></thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.permission}>
                <td><span className="font-mono text-xs">{p.permission}</span><span className="block text-xs text-muted">{p.description}</span></td>
                {roles.map((r) => <td key={r} className="text-center">{p.roles[r] ? <LuCircleCheck aria-label="allowed" className="inline text-green" /> : <span className="text-line-strong" aria-label="not allowed">—</span>}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
