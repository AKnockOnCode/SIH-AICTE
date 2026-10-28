import { useEffect, useMemo, useState } from "react";
import { LuEye, LuLock, LuRotateCcw, LuSave } from "react-icons/lu";
import { api } from "../api/client";
import type { CategoryRule, PreviewOut, RulesOut } from "../api/models";
import { useTitle } from "../components/layout";
import { Button, Card, Chip, ErrorState, Field, InlineError, Loading, Modal, PageHeader, SelectInput, Tabs } from "../components/ui";
import { fmtNum, humanize } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
type Settings = Record<string, { [k: string]: Json }>;
interface CatDraft extends CategoryRule {
  keywordsText: string;
  apply_sla_to_open: boolean;
}
const BLOCK_LABEL: Record<string, string> = {
  priority: "Priority scoring", matching: "Institution matching", conflict: "Overlap detection", lead: "Lead Bureau/Cell", sla: "SLA reminders",
  risk: "Risk Index",
};
const BLOCK_HELP: Record<string, string> = {
  priority: "Priority score = 100 × severity weight × (1 + capped modifiers) / (max weight × (1 + cap)); bands by score.",
  matching: "Entity-resolution thresholds: auto-link only above the first, officer review between the two.",
  conflict: "Windows and similarity thresholds for duplicate, related and conflict detection, and which regulatory actions count as favourable or adverse.",
  lead: "Weights for the suggested lead Bureau/Cell: subject competence, current handling, regulatory actions, workload.",
  sla: "Reminder and breach-prediction thresholds (category SLA days are set in the table).",
  risk: "Risk Index smoothing: recency half-life, outcome factors, intake fallback, prior strength and bands.",
};

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export function RulesPage() {
  useTitle("Priority Rules Editor");
  const { data, error, loading, reload } = useApi<RulesOut>("/api/rules");
  const { can, reloadReference, bump } = useSession();
  const ref = useRefData();
  const toast = useToast();
  const editable = can("rules.edit");
  const [tab, setTab] = useState<string>("categories");
  const [cats, setCats] = useState<CatDraft[]>([]);
  const [settings, setSettings] = useState<Settings>({});
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const save = useAction();
  const prev = useAction();

  const original = useMemo(() => (data?.categories ?? []) as unknown as CategoryRule[], [data]);
  useEffect(() => {
    if (!data) return;
    setCats(original.map((c) => ({ ...c, keywordsText: (c.keywords ?? []).join(", "), apply_sla_to_open: false })));
    setSettings(clone(data.settings as Settings));
    setPreview(null);
  }, [data, original]);

  const catChanges = useMemo(() => {
    const out: Record<string, Record<string, unknown>> = {};
    for (const d of cats) {
      const o = original.find((c) => c.code === d.code);
      if (!o) continue;
      const ch: Record<string, unknown> = {};
      if (d.label !== o.label) ch.label = d.label;
      if (Number(d.severity_level) !== o.severity_level) ch.severity_level = Number(d.severity_level);
      if (Number(d.severity_weight) !== o.severity_weight) ch.severity_weight = Number(d.severity_weight);
      if (Number(d.sla_days) !== o.sla_days) ch.sla_days = Number(d.sla_days);
      if (d.default_bureau !== o.default_bureau) ch.default_bureau = d.default_bureau;
      const kw = d.keywordsText.split(",").map((k) => k.trim().toLowerCase()).filter(Boolean);
      if (JSON.stringify([...kw].sort()) !== JSON.stringify([...(o.keywords ?? [])].sort())) ch.keywords = kw;
      if (Boolean(d.active) !== Boolean(o.active)) ch.active = Boolean(d.active);
      if (Object.keys(ch).length) out[d.code] = { ...ch, apply_sla_to_open: d.apply_sla_to_open && "sla_days" in ch };
    }
    return out;
  }, [cats, original]);
  const settingChanges = useMemo(() => {
    const out: Record<string, { [k: string]: Json }> = {};
    if (!data) return out;
    for (const [block, value] of Object.entries(settings)) {
      if (JSON.stringify(value) !== JSON.stringify((data.settings as Settings)[block])) out[block] = value;
    }
    return out;
  }, [settings, data]);
  const dirty = Object.keys(catChanges).length + Object.keys(settingChanges).length;

  const runPreview = async () => {
    const out = await prev.run(() => api.post<PreviewOut>("/api/rules/preview", { categories: catChanges, settings: settingChanges }));
    if (out) setPreview(out);
  };
  const runSave = async () => {
    const out = await save.run(async () => {
      let recomputed = 0;
      for (const [code, body] of Object.entries(catChanges)) recomputed = (await api.put<{ recomputed: number }>(`/api/rules/categories/${code}`, body)).recomputed;
      for (const [block, value] of Object.entries(settingChanges)) await api.put(`/api/rules/settings/${block}`, { value });
      return recomputed;
    });
    if (out !== undefined) {
      toast.push(`Rules saved and audited (before/after values). ${out ? `Priorities recomputed for ${fmtNum(out)} cases.` : ""}`);
      reloadReference();
      bump();
      reload();
    }
  };

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  return (
    <div>
      <PageHeader title="Priority and routing rules"
        subtitle="Severity, SLA, keywords and every scoring weight are stored as configuration in the database, not in code, so they can be aligned with AICTE policy."
        meta={<>
          <Chip tone="orange">{data.note}</Chip>
          {!editable && <Chip tone="neutral" icon={<LuLock aria-hidden />}>Read-only: only the Competent Authority can save changes; you can preview</Chip>}
        </>}
        actions={<>
          <Button icon={<LuEye aria-hidden />} busy={prev.busy} disabled={!dirty} onClick={runPreview}>Preview impact</Button>
          {editable && <Button variant="primary" icon={<LuSave aria-hidden />} busy={save.busy} disabled={!dirty || (preview !== null && !preview.valid)} onClick={runSave}>
            Save {dirty ? `${dirty} change${dirty === 1 ? "" : "s"}` : "changes"}</Button>}
          {editable && <Button variant="ghost" icon={<LuRotateCcw aria-hidden />} onClick={() => setResetOpen(true)}>Reset to defaults</Button>}
        </>} />
      <InlineError error={save.error ?? prev.error} />
      {preview && <PreviewCard p={preview} />}
      <Tabs value={tab} onChange={setTab} className="mb-3" tabs={[{ value: "categories", label: "Categories, SLA and keywords" },
        ...Object.keys(settings).map((b) => ({ value: b, label: BLOCK_LABEL[b] ?? humanize(b) }))]} />
      {tab === "categories" ? (
        <Card title="Complaint categories" subtitle="Changing SLA days affects new cases; tick ‘apply to open cases’ to move due dates of open cases too.">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th scope="col">Category</th><th scope="col">Severity (1–5)</th><th scope="col">Weight</th><th scope="col">SLA days</th>
                <th scope="col">Default Bureau/Cell</th><th scope="col">Escalation keywords</th><th scope="col">Active</th></tr></thead>
              <tbody>
                {cats.map((c, i) => {
                  const upd = (patch: Partial<CatDraft>) => setCats(cats.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  const changed = !!catChanges[c.code];
                  return (
                    <tr key={c.code} className={changed ? "bg-orange-soft/40" : ""}>
                      <td className="min-w-56">
                        <input aria-label={`${c.code} label`} className="field-input" value={c.label} onChange={(e) => upd({ label: e.target.value })} />
                        <span className="mt-1 block text-xs text-muted">{c.code}, {humanize(c.family)}</span>
                      </td>
                      <td><SelectInput aria-label={`${c.code} severity`} className="w-20" value={String(c.severity_level)} onChange={(v) => upd({ severity_level: Number(v) })}
                        options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} /></td>
                      <td><input aria-label={`${c.code} weight`} type="number" step="0.1" min={0.1} max={10} className="field-input w-24" value={c.severity_weight}
                        onChange={(e) => upd({ severity_weight: Number(e.target.value) })} /></td>
                      <td>
                        <input aria-label={`${c.code} SLA days`} type="number" min={1} max={365} className="field-input w-20" value={c.sla_days}
                          onChange={(e) => upd({ sla_days: Number(e.target.value) })} />
                        {Number(c.sla_days) !== original[i]?.sla_days && (
                          <label className="mt-1 flex items-center gap-1 text-xs"><input type="checkbox" checked={c.apply_sla_to_open}
                            onChange={(e) => upd({ apply_sla_to_open: e.target.checked })} />apply to open cases</label>
                        )}
                      </td>
                      <td><SelectInput aria-label={`${c.code} default bureau`} className="w-28" value={c.default_bureau} onChange={(v) => upd({ default_bureau: v })}
                        options={ref.bureaus.map((b) => ({ value: b.code, label: b.code }))} /></td>
                      <td className="min-w-64"><textarea aria-label={`${c.code} keywords`} rows={3} className="field-input text-xs" value={c.keywordsText}
                        onChange={(e) => upd({ keywordsText: e.target.value })} /></td>
                      <td><input aria-label={`${c.code} active`} type="checkbox" checked={Boolean(c.active)} onChange={(e) => upd({ active: e.target.checked ? 1 : 0 })} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card title={`${BLOCK_LABEL[tab] ?? humanize(tab)} settings`} subtitle={BLOCK_HELP[tab]}>
          {settings[tab] && <JsonForm value={settings[tab]} onChange={(v) => setSettings({ ...settings, [tab]: v as { [k: string]: Json } })} path={tab} />}
        </Card>
      )}
      <ResetDialog open={resetOpen} onClose={() => setResetOpen(false)} onDone={() => {
        setResetOpen(false);
        reloadReference();
        bump();
        reload();
      }} />
    </div>
  );
}

function JsonForm({ value, onChange, path }: { value: { [k: string]: Json }; onChange: (v: { [k: string]: Json }) => void; path: string }) {
  const help = typeof value.help === "string" ? value.help : null;
  return (
    <div className="space-y-3">
      {help && <p className="text-xs text-muted">{help}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(value).filter(([k, v]) => k !== "help" && (typeof v !== "object" || v === null || Array.isArray(v))).map(([k, v]) => {
          const set = (nv: Json) => onChange({ ...value, [k]: nv });
          const label = humanize(k);
          if (typeof v === "boolean") {
            return <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v} onChange={(e) => set(e.target.checked)} />{label}</label>;
          }
          if (typeof v === "number") {
            return <Field key={k} label={label}>{(id) => <input id={id} type="number" step={Number.isInteger(v) ? 1 : 0.01} className="field-input" value={v}
              onChange={(e) => set(e.target.value === "" ? 0 : Number(e.target.value))} />}</Field>;
          }
          if (Array.isArray(v)) {
            return <Field key={k} label={label} hint="Comma-separated" className="sm:col-span-2 lg:col-span-3">{(id) => <input id={id} className="field-input" value={v.join(", ")}
              onChange={(e) => set(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />}</Field>;
          }
          return <Field key={k} label={label}>{(id) => <input id={id} className="field-input" value={String(v ?? "")} onChange={(e) => set(e.target.value)} />}</Field>;
        })}
      </div>
      {Object.entries(value).filter(([, v]) => typeof v === "object" && v !== null && !Array.isArray(v)).map(([k, v]) => (
        <fieldset key={k} className="rounded-md border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-navy-ink">{humanize(k)}</legend>
          <JsonForm value={v as { [k: string]: Json }} onChange={(nv) => onChange({ ...value, [k]: nv })} path={`${path}.${k}`} />
        </fieldset>
      ))}
    </div>
  );
}

function PreviewCard({ p }: { p: PreviewOut }) {
  const bands = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
  return (
    <Card className="mb-4" title={p.valid ? "Impact preview (nothing saved yet)" : "These changes are not valid"} tone={p.valid ? "tint" : "alert"}>
      {!p.valid && <ul className="list-disc pl-5 text-sm text-red-ink">{p.errors.map((e) => <li key={e}>{e}</li>)}</ul>}
      {p.valid && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <p className="text-sm text-ink"><strong className="num">{fmtNum(p.band_changes)}</strong> of {fmtNum(p.open_cases)} open cases would change priority band;
              {" "}<strong className="num">{fmtNum(p.due_date_changes)}</strong> due dates would move.</p>
            {p.review_routing && <p className="mt-1 text-sm text-ink">Pending match reviews under the new thresholds: {p.review_routing.auto_link} auto-link,
              {" "}{p.review_routing.review} review, {p.review_routing.no_match} no match.</p>}
            <table className="data-table mt-2 w-auto">
              <thead><tr><th scope="col">Now ↓ / after →</th>{bands.map((b) => <th key={b} scope="col" className="num">{humanize(b)}</th>)}</tr></thead>
              <tbody>{bands.map((r) => <tr key={r}><th scope="row" className="text-left">{humanize(r)}</th>
                {bands.map((c) => <td key={c} className={`num ${r !== c && p.band_matrix[r]?.[c] ? "font-bold text-orange-ink" : ""}`}>{p.band_matrix[r]?.[c] ?? 0}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <div>
            <p className="text-xs font-semibold text-ink">Examples</p>
            {p.examples.length === 0 ? <p className="text-sm text-muted">No band changes.</p> : (
              <ul className="mt-1 space-y-0.5 text-sm">{p.examples.map((e) => (
                <li key={String(e.case_id)}>{String(e.case_id)}: {humanize(String(e.old_band))} {Number(e.old_score).toFixed(1)} → {humanize(String(e.new_band))} {Number(e.new_score).toFixed(1)}</li>))}</ul>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function ResetDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState("all");
  const { busy, error, run } = useAction();
  const toast = useToast();
  return (
    <Modal open={open} title="Reset rules to defaults" onClose={onClose}
      description="Replaces the stored configuration with the shipped defaults. The previous values stay in the audit trail."
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" busy={busy} disabled={text !== "RESET"} onClick={async () => {
          const out = await run(() => api.post("/api/rules/reset", { confirm: "RESET", scope }));
          if (out !== undefined) {
            toast.push("Rules reset to defaults.");
            setText("");
            onDone();
          }
        }}>Reset</Button>
      </>}>
      <div className="space-y-3">
        <Field label="What to reset">{(id) => <SelectInput id={id} value={scope} onChange={setScope}
          options={[{ value: "all", label: "Categories and all settings" }, { value: "categories", label: "Categories only" }, { value: "settings", label: "Settings only" }]} />}</Field>
        <Field label="Type RESET to confirm" required>{(id) => <input id={id} className="field-input" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />}</Field>
        <InlineError error={error} />
      </div>
    </Modal>
  );
}
