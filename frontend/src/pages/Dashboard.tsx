import { LuArrowUpRight, LuGitCompareArrows, LuTriangleAlert } from "react-icons/lu";
import type {
  CategoryLoad, CoordinationItem, DashboardOut, DashboardOverlaps, DemoLinks, MultiBureauRow, PriorityMixRow, RecentAlert, RegionLoad,
  StateLoad, Triage,
} from "../api/models";
import { Donut, HBars, Legend, StackedColumns, TrendChart, TriageSankey } from "../components/charts";
import { FilterBar, filterLink, urlFilters } from "../components/filters";
import { useTitle } from "../components/layout";
import { BureauTag, Card, Chip, ErrorState, Kpi, Loading, PageHeader, SyntheticBadge, TierChip } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, useLocation } from "../lib/router";
import { useRefData } from "../lib/session";
import { BAND_COLOR, BAND_ORDER, bureauColor, C, STATUS_COLOR } from "../lib/theme";

const FILTERS = ["dates", "bureau", "region", "state", "category"] as const;

export function DashboardPage() {
  useTitle("Command Dashboard");
  const { params } = useLocation();
  const query = urlFilters(params, [...FILTERS]);
  const { data, error, loading, reload } = useApi<DashboardOut>("/api/dashboard", query);
  const ref = useRefData();
  const link = (extra: Record<string, string | string[]>) => filterLink("/search", { ...query, ...extra });

  return (
    <div>
      <PageHeader title="Command dashboard"
        subtitle="Live aggregates over every Bureau/Cell. The date range selects cases by receipt date; statuses are as of today."
        meta={data && <><SyntheticBadge label={data.data_mode === "SYNTHETIC" ? "Synthetic dataset" : "Synthetic + entered records"} />
          <span className="text-xs text-muted">As of {data.as_of}, computed {fmtDateTime(data.generated_at)}</span></>} />
      <FilterBar show={[...FILTERS]} />
      {error && <ErrorState error={error} onRetry={reload} className="mb-4" />}
      {!data && loading && <Loading />}
      {data && (
        <div className={loading ? "opacity-70 transition-opacity" : ""}>
          <section aria-label="Key figures" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Received" value={data.kpis.received} color={C.blue} to={link({})} />
            <Kpi label="Pending" value={data.kpis.pending} color={C.orangeStrong} to={link({ status: ["RECEIVED", "PENDING"] })} />
            <Kpi label="Under process" value={data.kpis.under_process} color={C.blue} to={link({ status: ["UNDER_PROCESS"] })} />
            <Kpi label="Disposed" value={data.kpis.disposed} color={C.green} to={link({ status: ["DISPOSED"] })} />
            <Kpi label="Transferred" value={data.kpis.transferred} color={C.slateInk} to={link({ status: ["TRANSFERRED"] })}
              hint={`${fmtNum(data.kpis.ever_transferred)} moved at least once`} />
            <Kpi label="Overdue (beyond SLA)" value={data.kpis.overdue} color={C.red} to={link({ overdue: "true" })} />
          </section>
          <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
            <span>Escalated now <strong className="num text-ink">{fmtNum(data.kpis.escalated)}</strong></span>
            <span>Disposal rate <strong className="num text-ink">{fmtPct(data.kpis.disposal_rate)}</strong></span>
            <span>Disposed within SLA <strong className="num text-ink">{fmtPct(data.kpis.sla_compliance)}</strong></span>
            <span>Average time to dispose <strong className="num text-ink">{data.kpis.avg_disposal_days} days</strong></span>
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-7" title="Bureau-wise workload" subtitle="Open cases by status; click a bar to open those cases">
              <BureauWorkload data={data} link={link} />
            </Card>
            <Card className="xl:col-span-5" title="Priority mix" subtitle="Open cases by effective priority band">
              <PriorityMix rows={data.priority_mix as unknown as PriorityMixRow[]} link={link} />
            </Card>

            <Card className="xl:col-span-7" title="Coordination required"
              subtitle="Open overlap alerts across Bureaus/Cells — act before contradictory decisions are taken"
              actions={<Link to="/overlaps" className="text-sm font-semibold">All overlaps</Link>}>
              <Coordination overlaps={data.overlaps as unknown as DashboardOverlaps} multi={data.multi_bureau_count} />
            </Card>
            <Card className="xl:col-span-5" title="Guided demo scenario" tone="tint"
              subtitle="Hand-seeded synthetic story: Institution A appears in two silos">
              <DemoPanel demo={data.demo as unknown as DemoLinks} />
            </Card>

            <Card className="xl:col-span-7" title="Disposal trend" subtitle="Cases received (bars) and disposed (line) per month">
              <TrendChart points={data.trend} />
              <div className="mt-2"><Legend items={[{ label: "Received", color: "#9CC3E6", shape: "bar" }, { label: "Disposed", color: C.green, shape: "line" }]} /></div>
            </Card>
            <Card className="xl:col-span-5" title="Pending-case ageing" subtitle="Open cases by days since receipt, stacked by Bureau/Cell">
              <StackedColumns ariaLabel="Open cases by age bucket and bureau"
                columns={data.ageing.map((a) => ({ key: a.bucket, label: a.bucket.replace(" days", "d").replace("Over ", ">"), values: a.by_bureau }))}
                series={ref.bureaus.map((b) => ({ key: b.code, label: b.code, color: bureauColor(b.code) }))} />
              <div className="mt-2"><Legend items={ref.bureaus.map((b) => ({ label: b.code, color: bureauColor(b.code), shape: "bar" }))} /></div>
            </Card>

            <Card className="xl:col-span-7" title="Intake triage"
              subtitle="Where received cases went after de-duplication, and their priority band"
              actions={<span className="text-xs text-muted">{(data.triage as unknown as Triage).note}</span>}>
              <TriageSankey {...(data.triage as unknown as Triage)} />
            </Card>
            <Card className="xl:col-span-5" title="Alerts needing attention" subtitle="Newest unacknowledged in-app alerts for your role"
              actions={<Link to="/alerts?state=NEW" className="text-sm font-semibold">Alerts centre</Link>}>
              <RecentAlerts rows={data.recent_alerts as unknown as RecentAlert[]} />
            </Card>

            <Card className="xl:col-span-6" title="Region view" subtitle="Received, open and overdue cases by AICTE region">
              <RegionTable rows={data.by_region as unknown as RegionLoad[]} link={link} />
            </Card>
            <Card className="xl:col-span-6" title="Category and severity" subtitle="Highest severity first">
              <CategoryTable rows={data.by_category as unknown as CategoryLoad[]} link={link} />
            </Card>

            <Card className="xl:col-span-6" title="Institutions with open cases in several Bureaus/Cells"
              subtitle={`${fmtNum(data.multi_bureau_count)} institutions are handled by two or more silos at once`}>
              <MultiBureau rows={data.multi_bureau_institutions as unknown as MultiBureauRow[]} />
            </Card>
            <Card className="xl:col-span-6" title="State view" subtitle="States by cases received">
              <StateTable rows={data.by_state as unknown as StateLoad[]} link={link} />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function BureauWorkload({ data, link }: { data: DashboardOut; link: (x: Record<string, string | string[]>) => string }) {
  const series = [
    { key: "pending", label: "Pending", color: STATUS_COLOR.PENDING },
    { key: "under_process", label: "Under process", color: STATUS_COLOR.UNDER_PROCESS },
    { key: "transferred", label: "Transferred", color: STATUS_COLOR.TRANSFERRED },
    { key: "escalated", label: "Escalated", color: STATUS_COLOR.ESCALATED },
  ] as const;
  return (
    <>
      <HBars ariaLabel="Open cases per Bureau/Cell by status"
        rows={data.by_bureau.map((b) => ({
          key: b.code,
          label: <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: bureauColor(b.code) }} aria-hidden />{b.code}</span>,
          segments: series.map((s) => ({ key: s.key, value: b[s.key], color: s.color, label: s.label })),
          right: <span title={`${b.open_total} open, ${b.overdue} overdue, ${b.officers} officers`}>
            {fmtNum(b.open_total)} open{b.overdue ? <span className="text-red-ink"> / {fmtNum(b.overdue)} late</span> : null}
          </span>,
          to: link({ bureau: [b.code], open_only: "true" }),
        }))} />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <Legend items={series.map((s) => ({ label: s.label, color: s.color, shape: "bar" }))} />
        <p className="text-xs text-muted">
          Load per officer: {data.by_bureau.filter((b) => b.open_per_officer !== null).map((b) => `${b.code} ${b.open_per_officer}`).join(", ")}
        </p>
      </div>
    </>
  );
}

function PriorityMix({ rows, link }: { rows: PriorityMixRow[]; link: (x: Record<string, string | string[]>) => string }) {
  const map = new Map(rows.map((r) => [r.band, r.n]));
  const data = BAND_ORDER.map((b) => ({ key: b, label: humanize(b), value: map.get(b) ?? 0, color: BAND_COLOR[b] }));
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="flex flex-wrap items-center gap-6">
      <Donut data={data} center={<><span className="num text-xl font-bold text-ink">{fmtNum(total)}</span><span className="text-xs text-muted">open</span></>} />
      <ul className="space-y-2 text-sm">
        {data.map((d) => (
          <li key={d.key}>
            <Link to={link({ priority: [d.key], open_only: "true" })} className="flex items-center gap-2 text-ink no-underline hover:underline">
              <span className="inline-block h-3 w-3 rounded-full" style={{ background: d.color }} aria-hidden />
              <span className="w-16">{d.label}</span>
              <span className="num font-semibold">{fmtNum(d.value)}</span>
              <span className="num text-xs text-muted">{total ? fmtPct(d.value / total) : ""}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Coordination({ overlaps, multi }: { overlaps: DashboardOverlaps; multi: number }) {
  const tiers = ["CONFLICT", "DUPLICATE", "RELATED"];
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tiers.map((t) => (
          <Link key={t} to={`/overlaps?tier=${t}`} className="rounded-md border border-line px-3 py-2 no-underline hover:border-blue/50">
            <span className="num block text-xl font-bold" style={{ color: t === "CONFLICT" ? C.red : t === "DUPLICATE" ? C.green : C.orangeStrong }}>
              {fmtNum(overlaps.open_by_tier[t] ?? 0)}
            </span>
            <span className="text-xs text-muted">{humanize(t)} alerts open</span>
          </Link>
        ))}
        <Link to="/overlaps?cross_bureau=true" className="rounded-md border border-line px-3 py-2 no-underline hover:border-blue/50">
          <span className="num block text-xl font-bold text-navy-ink">{fmtNum(overlaps.cross_bureau_open)}</span>
          <span className="text-xs text-muted">span 2+ Bureaus/Cells</span>
        </Link>
      </div>
      <ul className="mt-3 divide-y divide-line">
        {overlaps.coordination_queue.map((o: CoordinationItem) => (
          <li key={o.id} className="py-2.5">
            <Link to={`/overlaps/${o.id}`} className="group flex flex-wrap items-start gap-x-3 gap-y-1 no-underline">
              <span className="mt-0.5"><TierChip tier={o.tier} /></span>
              <span className="min-w-0 flex-1">
                <span className={`block text-sm font-semibold ${o.tier === "CONFLICT" ? "text-red-ink" : "text-ink"} group-hover:underline`}>{o.headline}</span>
                <span className="block text-xs text-muted">
                  {o.id}, {o.institution_name}
                  {o.demo_tag === "INSTITUTION_A" && <strong className="text-navy-ink"> (Institution A demo)</strong>}
                </span>
              </span>
              <span className="flex items-center gap-2">
                {o.bureaus.map((b) => <BureauTag key={b} code={b} />)}
                {o.recommended_lead && <Chip tone="navy">Lead: {o.recommended_lead}</Chip>}
              </span>
            </Link>
          </li>
        ))}
        {overlaps.coordination_queue.length === 0 && <li className="py-4 text-sm text-muted">No open cross-bureau overlaps in this selection.</li>}
      </ul>
      <p className="mt-1 text-xs text-muted">{fmtNum(multi)} institutions currently have open cases in two or more Bureaus/Cells.</p>
    </div>
  );
}

function DemoPanel({ demo }: { demo: DemoLinks }) {
  const a = demo.institution_a;
  const steps = [
    a && { to: `/institutions/${a.id}`, text: `Open the consolidated profile of Institution A (${a.name}).` },
    demo.institution_a_conflict && { to: `/overlaps/${demo.institution_a_conflict}`,
      text: "See the RB renewal and the PGRC fee-fraud case side by side, with the suggested lead Bureau/Cell." },
    { to: "/cases/PGRC-5530", text: "Follow PGRC-5530: timeline, SLA bar and breach forecast." },
    demo.live_trigger_institution && demo.live_trigger_case && { to: `/cases/${demo.live_trigger_case}`,
      text: `Live trigger: as the RB officer, record a renewal action on ${demo.live_trigger_case} (${demo.live_trigger_institution.name}) and watch a new conflict alert appear.` },
    { to: "/watchlist", text: "Review the watch-list: rising risk, predicted SLA breaches and repeated serious cases." },
    { to: "/match-reviews", text: `Resolve ${demo.pending_match_reviews} pending institution-match reviews (entity resolution).` },
  ].filter((x): x is { to: string; text: string } => !!x);
  return (
    <ol className="space-y-2.5">
      {steps.map((s, i) => (
        <li key={s.to} className="flex gap-3">
          <span className="num mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-navy text-xs font-bold text-white">{i + 1}</span>
          <Link to={s.to} className="text-sm text-ink no-underline hover:text-blue-ink hover:underline">
            {s.text} <LuArrowUpRight aria-hidden className="inline text-blue" />
          </Link>
        </li>
      ))}
    </ol>
  );
}

const ALERT_ICON: Record<string, string> = { CRITICAL: "text-red-ink", WARNING: "text-orange-ink", INFO: "text-blue-ink" };

function RecentAlerts({ rows }: { rows: RecentAlert[] }) {
  if (!rows.length) return <p className="py-4 text-sm text-muted">No new alerts for your role.</p>;
  return (
    <ul className="divide-y divide-line">
      {rows.map((a) => (
        <li key={a.id} className="flex gap-2.5 py-2">
          {a.alert_type === "OVERLAP" ? <LuGitCompareArrows aria-hidden className={`mt-0.5 shrink-0 ${ALERT_ICON[a.severity]}`} />
            : <LuTriangleAlert aria-hidden className={`mt-0.5 shrink-0 ${ALERT_ICON[a.severity]}`} />}
          <div className="min-w-0 text-sm">
            <Link to={a.case_id ? `/cases/${a.case_id}` : a.institution_id ? `/institutions/${a.institution_id}` : "/alerts"}
              className="line-clamp-2 text-ink no-underline hover:underline">{a.title}</Link>
            <span className="text-xs text-muted">{humanize(a.alert_type)}, {humanize(a.severity)}, {fmtDateTime(a.created_at)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function RegionTable({ rows, link }: { rows: RegionLoad[]; link: (x: Record<string, string | string[]>) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.received));
  return (
    <table className="data-table">
      <thead><tr><th scope="col">Region</th><th scope="col" className="num">Received</th><th scope="col" className="num">Open</th>
        <th scope="col" className="num">Overdue</th><th scope="col" className="w-1/3">Share of received</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.code}>
            <td><Link to={link({ region: [r.code] })}>{r.name}</Link></td>
            <td className="num">{fmtNum(r.received)}</td>
            <td className="num">{fmtNum(r.open_total)}</td>
            <td className={`num ${r.overdue ? "font-semibold text-red-ink" : ""}`}>{fmtNum(r.overdue)}</td>
            <td><div className="h-2 rounded-full bg-slate-soft"><div className="h-2 rounded-full bg-blue" style={{ width: `${(r.received / max) * 100}%` }} /></div></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StateTable({ rows, link }: { rows: StateLoad[]; link: (x: Record<string, string | string[]>) => string }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="data-table">
        <thead><tr><th scope="col">State</th><th scope="col" className="num">Received</th><th scope="col" className="num">Open</th><th scope="col" className="num">Overdue</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.state}>
              <td><Link to={link({ state: [r.state] })}>{r.state}</Link></td>
              <td className="num">{fmtNum(r.received)}</td>
              <td className="num">{fmtNum(r.open_total)}</td>
              <td className={`num ${r.overdue ? "text-red-ink" : ""}`}>{fmtNum(r.overdue)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoryTable({ rows, link }: { rows: CategoryLoad[]; link: (x: Record<string, string | string[]>) => string }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="data-table">
        <thead><tr><th scope="col">Category</th><th scope="col">Severity</th><th scope="col" className="num">Received</th><th scope="col" className="num">Open</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.category_code}>
              <td><Link to={link({ category: [r.category_code] })}>{r.label}</Link></td>
              <td><span className="num" style={{ color: r.severity_level >= 4 ? C.red : r.severity_level === 3 ? C.orangeStrong : C.blue }}>
                {"●".repeat(r.severity_level)}<span className="text-line">{"●".repeat(5 - r.severity_level)}</span></span>
                <span className="sr-only">Severity {r.severity_level} of 5</span></td>
              <td className="num">{fmtNum(r.received)}</td>
              <td className="num">{fmtNum(r.open_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MultiBureau({ rows }: { rows: MultiBureauRow[] }) {
  if (!rows.length) return <p className="py-4 text-sm text-muted">No institution has open cases in more than one Bureau/Cell.</p>;
  return (
    <table className="data-table">
      <thead><tr><th scope="col">Institution</th><th scope="col">Bureaus/Cells with open cases</th><th scope="col" className="num">Open cases</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.institution_id}>
            <td><Link to={`/institutions/${r.institution_id}`}>{r.name}</Link></td>
            <td><span className="flex flex-wrap gap-2">{r.codes.map((c) => <BureauTag key={c} code={c} />)}</span></td>
            <td className="num">{fmtNum(r.open_cases)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
