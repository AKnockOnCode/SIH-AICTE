// One-click Pre-Decision Dossier: a print-optimised document (browser print / save as PDF), plus
// the server-generated PDF. Structured sections always come straight from the database.
import { useState, type ReactNode } from "react";
import { LuArrowLeft, LuDownload, LuPrinter, LuSparkles } from "react-icons/lu";
import { api } from "../api/client";
import type { DossierOut, RiskOut } from "../api/models";
import { useTitle } from "../components/layout";
import { Button, ErrorState, Loading } from "../components/ui";
import { fmtDate, fmtDateTime, fmtPct, fmtSigned, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";

type Row = Record<string, unknown>;
const s = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

function Section({ title, children, n }: { title: string; children: ReactNode; n: number }) {
  return (
    <section className="print-break-avoid mt-6 break-inside-avoid">
      <h2 className="border-b-2 border-navy pb-1 text-base font-bold text-navy-ink">{n}. {title}</h2>
      <div className="mt-2 text-[13px]">{children}</div>
    </section>
  );
}

function Table({ cols, rows, empty }: { cols: Array<[string, string, ((r: Row) => ReactNode)?]>; rows: Row[]; empty: string }) {
  if (!rows.length) return <p className="text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto print:overflow-visible">
    <table className="w-full border-collapse text-[12px]">
      <thead><tr>{cols.map(([k, label]) => <th key={k} scope="col" className="border-b border-line bg-tint px-2 py-1 text-left font-semibold">{label}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="break-inside-avoid">{cols.map(([k, , render]) => <td key={k} className="border-b border-[#e8edf5] px-2 py-1 align-top">{render ? render(r) : s(r[k])}</td>)}</tr>)}</tbody>
    </table>
    </div>
  );
}

export function DossierPage({ id }: { id: string }) {
  useTitle("Dossier", id);
  const [mode, setMode] = useState<"template" | "ai">("template");
  const { data, error, loading, reload } = useApi<DossierOut>(`/api/institutions/${encodeURIComponent(id)}/dossier`, { narrative: mode });
  const { me, ref } = useSession();
  const toast = useToast();
  const [pdfBusy, setPdfBusy] = useState(false);
  const officerName = (x: string) => ref?.officers.find((o) => o.id === x)?.display_name ?? (x || "—");
  if (error) return <div className="p-6"><ErrorState error={error} onRetry={reload} /></div>;
  if (!data) return <Loading label={loading ? "Generating dossier…" : "No data"} className="justify-center" />;
  const inst = data.institution as Row;
  const risk = data.risk as RiskOut | null;
  const prov = data.provenance as Row & { seed?: Row };
  const narrative = data.narrative as { text: string; source: string; validation: { ok?: boolean; note?: string } | null };
  return (
    <div className="mx-auto max-w-[900px] bg-white px-6 py-6 print:max-w-none print:px-0 print:py-0">
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-tint p-3 print:hidden">
        <Link to={`/institutions/${id}`} className="mr-auto inline-flex items-center gap-1 text-sm font-semibold"><LuArrowLeft aria-hidden /> Back to profile</Link>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={mode === "ai"} onChange={(e) => setMode(e.target.checked ? "ai" : "template")} />
          <LuSparkles aria-hidden className="text-navy" /> AI-assisted wording (optional)
        </label>
        <Button icon={<LuPrinter aria-hidden />} variant="primary" onClick={() => window.print()}>Print / save as PDF</Button>
        <Button icon={<LuDownload aria-hidden />} busy={pdfBusy} onClick={async () => {
          setPdfBusy(true);
          try {
            await api.download(`/api/institutions/${id}/dossier.pdf`, { narrative: mode }, `dossier-${id}.pdf`);
          } catch (e) {
            toast.push((e as Error).message, "error");
          } finally {
            setPdfBusy(false);
          }
        }}>Server PDF</Button>
      </div>

      <header className="border-b-4 border-navy pb-3">
        <p className="text-xs font-semibold text-muted">AgniDrishti Pre-Decision Dossier, generated {fmtDateTime(String(prov.generated_at))} for {me?.user.display_name}</p>
        <h1 className="mt-1 text-2xl font-bold text-navy-ink">{s(inst.name)}</h1>
        <p className="text-sm text-ink">AICTE Permanent ID {s(inst.permanent_id)}; AgniDrishti {s(inst.id)}; {s(inst.district)}, {s(inst.state)} ({humanize(String(inst.region))} region)</p>
        <p className="mt-2 rounded border border-orange bg-orange-soft px-3 py-1.5 text-xs font-semibold text-orange-ink">{data.disclaimer}</p>
      </header>

      <Section n={1} title="Summary">
        <p className="leading-relaxed">{narrative.text}</p>
        <p className="mt-1 text-xs text-muted">
          {narrative.source === "AI_ASSISTED" ? "AI-assisted wording, validated against database facts. " : "Deterministic template generated from database fields. "}
          {narrative.validation?.note ?? ""}
        </p>
      </Section>

      <Section n={2} title="Canonical profile and identifiers">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
          {([["Address", `${s(inst.address)}, ${s(inst.pincode)}`], ["Approved intake", `${s(inst.intake_total)} (${humanize(String(inst.intake_source ?? "unknown"))})`],
            ["Courses", Array.isArray(inst.courses) ? (inst.courses as string[]).join(", ") : "—"], ["Established", s(inst.established_year)],
            ["Trust / society", `${s(inst.trust)}${inst.trust_provenance ? ` (${String(inst.trust_provenance)})` : ""}`], ["Known aliases", data.aliases.join("; ") || "—"]] as Array<[string, string]>)
            .map(([k, v]) => <div key={k}><dt className="text-[11px] text-muted">{k}</dt><dd>{v}</dd></div>)}
        </dl>
        <p className="mt-2">Cases on file: {s((data.summary as Row).total_cases)}; open: {s((data.summary as Row).open_cases)}; overdue: {s((data.summary as Row).overdue_open)}.</p>
      </Section>

      <Section n={3} title="Institution Risk Index and forecast">
        {risk ? (
          <>
            <p><strong className="text-lg">{risk.score.toFixed(0)}/100</strong> {humanize(risk.band)}, {humanize(risk.trend).toLowerCase()} ({fmtSigned(risk.delta_6m)} in 6 months), data confidence {humanize(risk.confidence).toLowerCase()}.</p>
            <p className="mt-1">Probability of a serious complaint in the next 6 months: <strong>{fmtPct(risk.forecast.probability)}</strong> (80% range {fmtPct(risk.forecast.interval_80[0])}–{fmtPct(risk.forecast.interval_80[1])};
              {" "}{humanize(risk.forecast.status).toLowerCase()}, {humanize(risk.forecast.confidence).toLowerCase()} confidence).</p>
            <p className="mt-1 text-xs text-muted">Components: severity-weighted load {risk.components.severity_weighted_load.toFixed(1)} from {risk.components.cases_considered} cases; raw rate {risk.components.raw_rate.toFixed(1)} smoothed to {risk.components.shrunk_rate.toFixed(1)} per 1,000 students (credibility {fmtPct(risk.components.credibility)}); outcome coverage {fmtPct(risk.components.outcome_coverage)}.</p>
            <ul className="mt-1 list-disc pl-5 text-xs text-muted">{risk.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          </>
        ) : <p className="text-muted">Not available.</p>}
      </Section>

      <Section n={4} title="Duplicate, related and conflict alerts">
        <Table empty="No overlap alerts." rows={data.overlaps} cols={[
          ["id", "Alert"], ["tier", "Tier", (r) => humanize(String(r.tier))], ["headline", "Headline", (r) => <strong className={r.tier === "CONFLICT" ? "text-red-ink" : ""}>{s(r.headline)}</strong>],
          ["cases", "Cases", (r) => (r.cases as string[]).join(", ")], ["rules", "Why", (r) => <ul className="list-disc pl-4">{(r.rules as string[]).map((x) => <li key={x}>{x}</li>)}</ul>],
          ["recommended_lead", "Lead", (r) => (r.decided_lead ? `${String(r.decided_lead)} (agreed)` : `${s(r.recommended_lead)} (suggested)`)], ["status", "Status", (r) => humanize(String(r.status))],
        ]} />
      </Section>

      <Section n={5} title="Open cases and current responsibility">
        <Table empty="No open cases." rows={data.open_cases} cols={[
          ["id", "Case"], ["category", "Category", (r) => `${s(r.category)} (S${s(r.severity)})`], ["bureau", "Bureau"], ["officer", "Officer"], ["status", "Status"],
          ["priority", "Priority"], ["sla", "SLA"], ["last_action", "Last action", (r) => <>{s(r.last_action)}<span className="block text-muted">{fmtDate(String(r.last_action_at ?? ""))}</span></>],
          ["next_action", "Next action", (r) => <>{s(r.next_action)}<span className="block text-muted">{r.next_action_due ? `due ${fmtDate(String(r.next_action_due))}` : ""}</span></>],
        ]} />
      </Section>

      <Section n={6} title="Pending SLAs, predicted breaches and escalations">
        <Table empty="No case is overdue or due within 3 days." rows={data.pending_sla} cols={[["id", "Case"], ["bureau", "Bureau"], ["sla", "SLA"], ["due_date", "Due", (r) => fmtDate(String(r.due_date))], ["officer", "Officer"]]} />
        <p className="mt-2 font-semibold">Predicted SLA breaches (model estimate)</p>
        <Table empty="None predicted." rows={data.predicted_breaches} cols={[["id", "Case"], ["bureau", "Bureau"], ["due_date", "Due", (r) => fmtDate(String(r.due_date))],
          ["breach_probability", "Probability", (r) => fmtPct(Number(r.breach_probability))], ["officer", "Officer"]]} />
        <p className="mt-2 font-semibold">Escalations</p>
        <Table empty="No open escalation." rows={data.escalations} cols={[["id", "Case"], ["bureau", "Bureau"], ["escalation_level", "Level"], ["status", "Status"]]} />
      </Section>

      <Section n={7} title="Recommended before any decision">
        <ul className="list-disc space-y-1 pl-5">{data.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
        <p className="mt-1 text-xs text-muted">Recommendations are generated from rules over the records above; the decision remains with the competent officer.</p>
      </Section>

      <Section n={8} title="Recent actions across Bureaus/Cells">
        <Table empty="No recent actions." rows={data.recent_actions} cols={[["action_at", "When", (r) => fmtDateTime(String(r.action_at))], ["case_id", "Case"],
          ["label", "Action"], ["actor_label", "By", (r) => officerName(String(r.actor_label ?? ""))], ["bureau_code", "Bureau"], ["remarks", "Remarks"]]} />
      </Section>

      <Section n={9} title="Complete case history">
        <Table empty="No cases." rows={data.case_history} cols={[["id", "Case"], ["received", "Received", (r) => fmtDate(String(r.received))], ["category", "Category"],
          ["bureau", "Bureau"], ["status", "Status"], ["outcome", "Outcome", (r) => (r.outcome ? humanize(String(r.outcome)) : "—")], ["disposed", "Disposed", (r) => fmtDate(r.disposed as string | null)]]} />
      </Section>

      <Section n={10} title="Public signals (context only, not complaints)">
        <Table empty="No public signal is linked to this institution." rows={data.public_signals} cols={[["title", "Title"], ["publisher", "Publisher"],
          ["verification", "Verification", (r) => (r.verification === "SYNTHETIC" ? "Synthetic demo example" : humanize(String(r.verification)))],
          ["source_url", "Source", (r) => (r.source_url ? <a href={String(r.source_url)} target="_blank" rel="noopener noreferrer" className="break-all">{String(r.source_url)}</a> : "No link")]]} />
      </Section>

      <Section n={11} title="Data provenance">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {([["Generated", `${fmtDateTime(String(prov.generated_at))} by ${s(prov.generated_by)}`], ["Data as of", s(prov.as_of)], ["Application version", s(prov.app_version)],
            ["Data", s(prov.data)], ["Seed", prov.seed ? `${s(prov.seed.seed)} (anchor ${s(prov.seed.anchor_date)}), fingerprint ${String(prov.seed.fingerprint ?? "").slice(0, 16)}…` : "—"],
            ["Risk method", s(prov.risk_method)], ["Forecast method", s(prov.forecast_method)], ["Breach method", s(prov.breach_method)]] as Array<[string, string]>)
            .map(([k, v]) => <div key={k}><dt className="text-muted">{k}</dt><dd>{v}</dd></div>)}
        </dl>
      </Section>
      <footer className="mt-8 border-t border-line pt-2 text-[11px] text-muted">{data.disclaimer} Generated by AgniDrishti (SIH 2026 prototype); not an official AICTE document.</footer>
    </div>
  );
}
