import { useState } from "react";
import { LuDownload, LuExternalLink, LuFileText, LuGitCompareArrows, LuNetwork } from "react-icons/lu";
import { api } from "../api/client";
import type {
  AliasRow, InstitutionDetail, InstitutionOverlap, InstitutionRecord, InstitutionTimelineRow, MasterCaseBrief, MatchReviewBrief, RiskOut,
  SignalBrief, SisterInstitution, TrustRecord,
} from "../api/models";
import { CaseTable } from "../components/cases";
import { Gauge, Lollipop } from "../components/charts";
import { useTitle } from "../components/layout";
import {
  BureauTag, Button, Card, Chip, Disclosure, ErrorState, KeyValues, Loading, PageHeader, RiskChip, SyntheticBadge, Tabs, TierChip,
} from "../components/ui";
import { demoLabel, fmtDate, fmtDateTime, fmtNum, fmtPct, fmtSigned, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useRefData } from "../lib/session";
import { useToast } from "../lib/toast";
import { RISK_COLOR } from "../lib/theme";

export function InstitutionPage({ id }: { id: string }) {
  const { data, error, loading, reload } = useApi<InstitutionDetail>(`/api/institutions/${encodeURIComponent(id)}`);
  const inst = data?.institution as InstitutionRecord | undefined;
  useTitle("Institution Profile", inst ? `AICTE ID: ${inst.permanent_id ?? "not known"}` : id);
  const toast = useToast();
  const [busyPdf, setBusyPdf] = useState(false);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || !inst) return loading ? <Loading /> : null;
  const trust = data.trust as TrustRecord | null;
  const aliases = data.aliases as unknown as AliasRow[];
  const overlaps = data.overlaps as unknown as InstitutionOverlap[];
  const activeConflict = overlaps.find((o) => o.tier === "CONFLICT" && (o.status === "OPEN" || o.status === "UNDER_REVIEW"));
  const pdf = async () => {
    setBusyPdf(true);
    try {
      await api.download(`/api/institutions/${inst.id}/dossier.pdf`, undefined, `dossier-${inst.id}.pdf`);
    } catch (e) {
      toast.push((e as Error).message, "error");
    } finally {
      setBusyPdf(false);
    }
  };
  return (
    <div>
      <PageHeader title={inst.name}
        subtitle={`${inst.institution_type ?? "Institution"}, ${inst.district ? `${inst.district}, ` : ""}${inst.state}`}
        meta={<>
          {inst.is_synthetic ? <SyntheticBadge label="Synthetic institution record" /> : <Chip tone="blue">Imported record</Chip>}
          {inst.demo_tag === "INSTITUTION_A" && <Chip tone="navy">Demo: Institution A</Chip>}
          {inst.demo_tag && inst.demo_tag !== "INSTITUTION_A" && <Chip tone="navy">Demo: {demoLabel(inst.demo_tag)}</Chip>}
          <RiskChip band={data.risk.band} score={data.risk.score} />
        </>}
        actions={<>
          <Button variant="primary" icon={<LuFileText aria-hidden />} onClick={() => window.open(`/institutions/${inst.id}/dossier`, "_blank")}>
            Pre-decision dossier
          </Button>
          <Button icon={<LuDownload aria-hidden />} busy={busyPdf} onClick={pdf}>Dossier PDF</Button>
        </>} />

      {activeConflict && (
        <Link to={`/overlaps/${activeConflict.id}`}
          className="mb-4 flex items-center justify-center gap-2 rounded-lg border-2 border-red bg-red-soft px-4 py-3 text-center font-bold text-red-ink no-underline">
          <LuGitCompareArrows aria-hidden /> Potential Overlapping Cases – Coordination Required
        </Link>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Canonical profile" tone="tint">
          <KeyValues items={[
            ["AICTE Permanent ID", inst.permanent_id ?? "Not known"],
            ["AgniDrishti ID", inst.id],
            ["Address", [inst.address_line, inst.pincode].filter(Boolean).join(", ") || "—"],
            ["Region / State / District", `${humanize(inst.region_code)}, ${inst.state}, ${inst.district ?? "—"}`],
            ["Approved intake", inst.intake_total ? `${fmtNum(inst.intake_total)} (${humanize(inst.intake_source ?? "unknown")})` : "Not known"],
            ["Courses", inst.courses.length ? inst.courses.join(", ") : "—"],
            ["Established", inst.established_year ?? "—"],
            ["Trust / society", trust ? <span><Link to={`/graph?trust=${trust.id}`}>{trust.name}</Link>
              <span className="block text-xs text-muted">{trust.provenance}</span></span> : "None recorded"],
          ]} />
          {aliases.length > 0 && (
            <div className="mt-3">
              <p className="text-xs text-muted">Known aliases and spelling variants</p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {aliases.map((a) => <li key={a.alias}><Chip tone="neutral" title={`${humanize(a.alias_type)}, source ${a.source}`}>{a.alias}</Chip></li>)}
              </ul>
            </div>
          )}
          {(data.sister_institutions as unknown as SisterInstitution[]).length > 0 && (
            <div className="mt-3">
              <p className="text-xs text-muted">Other institutions run by the same trust</p>
              <ul className="mt-1 space-y-0.5 text-sm">
                {(data.sister_institutions as unknown as SisterInstitution[]).map((s) => (
                  <li key={s.id}><Link to={`/institutions/${s.id}`}>{s.name}</Link> <span className="text-xs text-muted">{s.district}, {s.state}</span></li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <RiskCard risk={data.risk} />

        <Card className="xl:col-span-7" title="Complaint history (severity)" subtitle="Highest severity reached each year; bubble shows the number of cases">
          <Lollipop points={data.history_by_year} />
        </Card>
        <Card className="xl:col-span-5" title="Who is handling it now" subtitle="Open cases by responsible Bureau/Cell and officers">
          {data.responsibility.length === 0 ? <p className="text-sm text-muted">No open cases.</p> : (
            <ul className="space-y-3">
              {data.responsibility.map((r) => (
                <li key={r.bureau_code} className="rounded-md border border-line p-3">
                  <p className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><BureauTag code={r.bureau_code} />
                    <span className="text-sm">{r.bureau_name}</span></span>
                    <span className="num text-sm font-semibold">{r.open_cases} open</span></p>
                  <p className="mt-1 text-xs text-muted">{r.officers.length ? r.officers.join(", ") : "No officer assigned"}</p>
                  <p className="mt-1 flex flex-wrap gap-2 text-xs">{r.case_ids.map((cid) => <Link key={cid} to={`/cases/${cid}`}>{cid}</Link>)}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-12" title="Overlaps, duplicates and conflicts" subtitle="Alerts raised across Bureaus/Cells for this institution">
          {overlaps.length === 0 ? <p className="text-sm text-muted">No overlap alerts.</p> : (
            <table className="data-table">
              <thead><tr><th scope="col">Alert</th><th scope="col">Tier</th><th scope="col">Headline</th><th scope="col">Cases</th>
                <th scope="col">Bureaus</th><th scope="col">Status</th><th scope="col">Lead</th></tr></thead>
              <tbody>
                {overlaps.map((o) => (
                  <tr key={o.id}>
                    <td className="whitespace-nowrap"><Link to={`/overlaps/${o.id}`} className="font-semibold">{o.id}</Link></td>
                    <td><TierChip tier={o.tier} /></td>
                    <td className={o.tier === "CONFLICT" ? "font-semibold text-red-ink" : ""}>{o.headline}</td>
                    <td className="text-xs">{o.cases.map((c) => <Link key={c} to={`/cases/${c}`} className="mr-2">{c}</Link>)}</td>
                    <td><span className="flex gap-2">{o.bureaus.map((b) => <BureauTag key={b} code={b} />)}</span></td>
                    <td>{humanize(o.status)}</td>
                    <td>{o.decided_lead ? <Chip tone="green">{o.decided_lead} (agreed)</Chip> : o.recommended_lead ? <Chip tone="navy">{o.recommended_lead} (suggested)</Chip> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(data.master_cases as unknown as MasterCaseBrief[]).length > 0 && (
            <p className="mt-3 text-sm">Master Cases: {(data.master_cases as unknown as MasterCaseBrief[]).map((m) => (
              <Link key={m.id} to={`/master-cases/${m.id}`} className="mr-3">{m.id} ({humanize(m.kind)}, {humanize(m.status)})</Link>))}</p>
          )}
        </Card>

        <CasesAndTimeline data={data} />

        <Card className="xl:col-span-6" title="Institution-match reviews" subtitle="Complaint records whose institution name needs an officer’s confirmation">
          {(data.match_reviews as unknown as MatchReviewBrief[]).length === 0 ? <p className="text-sm text-muted">No reviews involve this institution.</p> : (
            <ul className="divide-y divide-line text-sm">
              {(data.match_reviews as unknown as MatchReviewBrief[]).map((m) => (
                <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>“{m.raw_name}” <span className="text-xs text-muted">from {m.source_ref ?? "intake"}, best confidence {fmtPct(m.best_confidence)}</span></span>
                  <span className="flex items-center gap-2"><Chip tone={m.status === "PENDING" ? "orange" : "neutral"}>{humanize(m.status)}</Chip>
                    {m.status === "PENDING" && <Link to={`/match-reviews?focus=${m.id}`} className="text-xs font-semibold">Review</Link>}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="xl:col-span-6" title="Public signals" subtitle="Context from public sources; never a complaint or a finding"
          actions={<Link to="/signals" className="text-sm font-semibold">All signals</Link>}>
          {(data.public_signals as unknown as SignalBrief[]).length === 0 ? <p className="text-sm text-muted">No public signal is linked to this institution.</p> : (
            <ul className="space-y-2 text-sm">
              {(data.public_signals as unknown as SignalBrief[]).map((s) => (
                <li key={s.id} className="rounded-md border border-line p-2.5">
                  <p className="font-semibold text-ink">{s.title}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <Chip tone={s.verification === "SYNTHETIC" ? "neutral" : s.verification === "VERIFIED_SOURCE" ? "green" : "orange"}>
                      {s.verification === "SYNTHETIC" ? "Synthetic demo signal" : humanize(s.verification)}</Chip>
                    {s.publisher}, match {humanize(s.match_status)} {s.match_confidence !== null ? fmtPct(s.match_confidence) : ""}
                    {s.source_url && <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1">Source <LuExternalLink aria-hidden /></a>}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function RiskCard({ risk }: { risk: RiskOut }) {
  const color = RISK_COLOR[risk.band] ?? "#8A94A6";
  const c = risk.components;
  const f = risk.forecast;
  return (
    <Card className="xl:col-span-7" title="Institution Risk Index" subtitle={risk.disclaimer}>
      <div className="flex flex-wrap items-center gap-6">
        <Gauge value={risk.score} color={color} label="Risk Index" />
        <div className="min-w-48 flex-1">
          <p className="text-lg font-bold" style={{ color }}>{humanize(risk.band)} risk</p>
          <p className={`text-sm font-semibold ${risk.trend === "RISING" ? "text-red-ink" : risk.trend === "FALLING" ? "text-green-ink" : "text-ink"}`}>
            {humanize(risk.trend)} ({fmtSigned(risk.delta_6m)} in 6 months; was {risk.score_6m_ago.toFixed(0)})
          </p>
          <p className="mt-1 text-xs text-muted">Data confidence: {humanize(risk.confidence)}. {risk.explanation}</p>
        </div>
        <div className="rounded-md border border-line bg-tint p-3 text-sm">
          <p className="text-xs text-muted">Serious complaint in next 6 months</p>
          <p className="num text-2xl font-bold text-navy-ink">{fmtPct(f.probability)}</p>
          <p className="text-xs text-muted">80% range {fmtPct(f.interval_80[0])}–{fmtPct(f.interval_80[1])}</p>
          <p className="mt-1 text-xs"><Chip tone={f.status === "FITTED" ? "green" : "orange"}>{humanize(f.status)}</Chip></p>
          <p className="mt-1 text-xs text-muted">{humanize(f.confidence)} confidence, trend {humanize(f.trend).toLowerCase()}</p>
        </div>
      </div>
      <Disclosure summary="How the score is built (components, smoothing, caveats)">
        <KeyValues cols={3} items={[
          ["Severity-weighted load (decayed)", c.severity_weighted_load.toFixed(1)],
          ["Cases considered", `${c.cases_considered} (first ${fmtDate(c.first_case)}, last ${fmtDate(c.last_case)})`],
          ["Share from last 12 months", fmtPct(c.recent_12m_share)],
          ["Outcome coverage", `${fmtPct(c.outcome_coverage)} of cases have an outcome`],
          ["Exposure", c.intake_known ? `${c.exposure_thousand_students} thousand students (intake)` : "Intake unknown: fallback used"],
          ["Raw rate → smoothed rate", `${c.raw_rate.toFixed(1)} → ${c.shrunk_rate.toFixed(1)} per 1,000 students`],
          ["Population / median rate", `${c.population_rate.toFixed(1)} / ${c.median_rate.toFixed(1)}`],
          ["Credibility weight", `${fmtPct(c.credibility)} (prior strength ${c.prior_strength})`],
          ["Recency half-life", `${c.half_life_days} days`],
          ["Serious cases, last 12 months", c.serious_last_12m],
          ["Forecast events (last / previous 6 months)", `${f.events_last_6m} / ${f.events_prev_6m}`],
          ["Hawkes parameters", Object.entries(f.params).map(([k, val]) => `${k} ${val}`).join(", ") || "—"],
        ]} />
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted">
          {[...risk.caveats, ...f.notes].map((x) => <li key={x}>{x}</li>)}
        </ul>
      </Disclosure>
    </Card>
  );
}

function CasesAndTimeline({ data }: { data: InstitutionDetail }) {
  const [tab, setTab] = useState<"open" | "all" | "timeline">("open");
  const ref = useRefData();
  const open = data.cases.filter((c) => c.status !== "DISPOSED");
  const timeline = data.timeline as unknown as InstitutionTimelineRow[];
  return (
    <Card className="xl:col-span-12" title="Consolidated cases across all Bureaus/Cells"
      actions={<Link to={`/search?institution_id=${(data.institution as InstitutionRecord).id}`} className="text-sm font-semibold">Open in search</Link>}>
      <Tabs value={tab} onChange={setTab} className="mb-3" tabs={[
        { value: "open", label: "Open", count: open.length },
        { value: "all", label: "All cases", count: data.cases.length },
        { value: "timeline", label: "Chronological timeline", count: timeline.length },
      ]} />
      {tab !== "timeline" ? <CaseTable rows={tab === "open" ? open : data.cases} showInstitution={false} /> : (
        <ol className="max-h-[520px] space-y-2 overflow-auto pr-2">
          {timeline.map((t, i) => (
            <li key={`${t.case_id}-${i}`} className="grid grid-cols-[150px_90px_1fr] gap-3 border-b border-line pb-2 text-sm last:border-0">
              <span className="text-xs text-muted">{fmtDateTime(t.action_at)}</span>
              <Link to={`/cases/${t.case_id}`} className="text-xs font-semibold">{t.case_id}</Link>
              <span><span className="font-semibold text-ink">{ref.actionLabel(t.action_type)}</span>
                <span className="text-xs text-muted"> by {t.actor_label}{t.bureau_code ? ` (${t.bureau_code})` : ""}</span>
                {t.remarks && <span className="block text-xs text-ink">{t.remarks}</span>}</span>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-2 text-xs text-muted"><LuNetwork aria-hidden className="mr-1 inline" />Cases from every silo are linked to this record through the Institution Master (entity resolution with officer confirmation).</p>
    </Card>
  );
}
