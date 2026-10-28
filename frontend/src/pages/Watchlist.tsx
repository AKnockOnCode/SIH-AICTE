import { LuArrowDown, LuArrowUp, LuFileText, LuMinus } from "react-icons/lu";
import type { WatchInstitution, WatchlistOut } from "../api/models";
import { useTitle } from "../components/layout";
import { BandChip, BureauTag, Card, Chip, Empty, ErrorState, Loading, MultiSelect, PageHeader, SelectInput, Tabs, type Tone } from "../components/ui";
import { daysLabel, demoLabel, fmtDate, fmtDateTime, fmtPct, fmtSigned, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useRefData } from "../lib/session";
import { RISK_COLOR } from "../lib/theme";

const REASON_LABEL: Record<string, string> = {
  HIGH_RISK: "High risk index", RISING_RISK: "Rising risk", FORECAST: "Serious complaint likely", CONFLICT: "Cross-bureau conflict",
  OVERDUE: "Overdue cases", REPEATED_SERIOUS: "Repeated serious cases", PREDICTED_BREACH: "Predicted SLA breach", DUE_SOON: "Due within days",
};
const REASON_TONE: Record<string, Tone> = {
  HIGH_RISK: "red", CONFLICT: "red", RISING_RISK: "orange", FORECAST: "orange", OVERDUE: "red", REPEATED_SERIOUS: "navy",
  PREDICTED_BREACH: "orange", DUE_SOON: "blue",
};
const SORTS: Record<string, (a: WatchInstitution, b: WatchInstitution) => number> = {
  attention: (a, b) => b.attention_score - a.attention_score || b.risk_score - a.risk_score,
  risk: (a, b) => b.risk_score - a.risk_score,
  rising: (a, b) => b.delta_6m - a.delta_6m,
  forecast: (a, b) => b.forecast_probability - a.forecast_probability,
  overdue: (a, b) => b.overdue_cases - a.overdue_cases,
};

export function WatchlistPage() {
  useTitle("Watch-list");
  const { params } = useLocation();
  const ref = useRefData();
  const tab = params.get("tab") === "cases" ? "cases" : "institutions";
  const reasons = listParam(params, "reason");
  const regions = listParam(params, "region");
  const sort = params.get("sort") ?? "attention";
  const { data, error, loading, reload } = useApi<WatchlistOut>("/api/watchlist", { reason: reasons, region: regions });
  const insts = data ? [...data.institutions].sort(SORTS[sort] ?? SORTS.attention) : [];
  return (
    <div>
      <PageHeader title="Watch-list"
        subtitle="Institutions and cases that need attention now: high or rising risk, likely serious complaints, overdue or soon-due cases, predicted SLA breaches and cross-bureau conflicts. Each entry shows why it is listed."
        meta={data && <span className="text-xs text-muted">{data.disclaimer}</span>} />
      <Tabs value={tab} onChange={(t) => setQuery({ tab: t === "institutions" ? null : t })} className="mb-3"
        tabs={[{ value: "institutions", label: "Institutions", count: data?.institutions.length }, { value: "cases", label: "Cases at risk of breaching SLA", count: data?.cases.length }]} />
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
        <MultiSelect label="Reason" className="w-full sm:w-64" value={reasons} onChange={(v) => setQuery({ reason: v })}
          options={Object.keys(REASON_LABEL).map((k) => ({ value: k, label: `${REASON_LABEL[k]}${data?.reason_counts[k] !== undefined ? ` (${data.reason_counts[k]})` : ""}` }))} />
        <MultiSelect label="Region" className="w-full sm:w-52" value={regions} onChange={(v) => setQuery({ region: v })}
          options={ref.regions.map((r) => ({ value: r.code, label: r.name }))} />
        {tab === "institutions" && (
          <label className="flex flex-col text-xs font-semibold text-ink">Sort by
            <SelectInput className="mt-1 w-56 font-normal" value={sort} onChange={(v) => setQuery({ sort: v === "attention" ? null : v })}
              options={[{ value: "attention", label: "Most reasons / attention" }, { value: "risk", label: "Highest risk index" }, { value: "rising", label: "Fastest rising" },
                { value: "forecast", label: "Highest forecast probability" }, { value: "overdue", label: "Most overdue cases" }]} />
          </label>
        )}
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && tab === "institutions" && (insts.length === 0 ? <Empty title="No institution matches these reasons" /> : (
        <ul className="space-y-3">
          {insts.map((w) => <InstitutionEntry key={w.institution_id} w={w} />)}
        </ul>
      ))}
      {data && tab === "cases" && (data.cases.length === 0 ? <Empty title="No case is predicted to breach its SLA" /> : (
        <Card title="Open cases likely to miss their due date" subtitle="Cox model estimate on synthetic history; overdue cases are listed separately as facts in Alerts">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th scope="col">Case</th><th scope="col">Institution</th><th scope="col">Bureau</th><th scope="col">Category</th>
                <th scope="col">Due</th><th scope="col" className="num">Breach probability</th><th scope="col">Main driver</th><th scope="col">Priority</th></tr></thead>
              <tbody>
                {data.cases.map((c) => (
                  <tr key={c.case_id}>
                    <td><Link to={`/cases/${c.case_id}`} className="font-semibold">{c.case_id}</Link><span className="block text-xs text-muted">{humanize(c.status)}</span></td>
                    <td>{c.institution_id ? <Link to={`/institutions/${c.institution_id}`}>{c.institution_name}</Link> : "—"}</td>
                    <td><BureauTag code={c.bureau_code} /></td>
                    <td>{ref.categoryLabel(c.category_code)}</td>
                    <td className="whitespace-nowrap">{fmtDate(c.due_date)}<span className="block text-xs text-orange-ink">{daysLabel(c.days_remaining)}</span></td>
                    <td className="num"><span className={`font-bold ${c.band === "HIGH" ? "text-red-ink" : "text-orange-ink"}`}>{fmtPct(c.probability)}</span></td>
                    <td className="max-w-72 text-xs">{c.top_factor ?? "—"}{c.historical && <span className="block text-muted">{c.historical}</span>}</td>
                    <td><BandChip band={c.priority_band} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}

function InstitutionEntry({ w }: { w: WatchInstitution }) {
  const TrendIcon = w.trend === "RISING" ? LuArrowUp : w.trend === "FALLING" ? LuArrowDown : LuMinus;
  return (
    <li className="rounded-lg border border-line bg-white p-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr_1fr_auto]">
        <div className="min-w-0">
          <Link to={`/institutions/${w.institution_id}`} className="text-base font-semibold">{w.name}</Link>
          <p className="text-xs text-muted">{w.district ? `${w.district}, ` : ""}{w.state}, {humanize(w.region_code)}{w.trust_name ? `. Trust: ${w.trust_name}` : ""}</p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {w.reasons.map((r) => <li key={r.code + r.label} className="max-w-full"><Chip wrap tone={REASON_TONE[r.code] ?? "neutral"}>{r.label}</Chip></li>)}
          </ul>
          {w.demo_tag && <p className="mt-1 text-xs text-navy-ink">Demo scenario: {demoLabel(w.demo_tag)}</p>}
        </div>
        <div>
          <p className="text-xs text-muted">Risk index</p>
          <p className="flex items-center gap-2">
            <span className="num text-2xl font-bold" style={{ color: RISK_COLOR[w.risk_band] }}>{w.risk_score.toFixed(0)}</span>
            <span className={`inline-flex items-center gap-1 text-sm font-semibold ${w.trend === "RISING" ? "text-red-ink" : w.trend === "FALLING" ? "text-green-ink" : "text-muted"}`}>
              <TrendIcon aria-hidden />{fmtSigned(w.delta_6m)} in 6 mo</span>
          </p>
          <p className="text-xs text-muted">{humanize(w.risk_band)}, {humanize(w.risk_confidence).toLowerCase()} data confidence</p>
        </div>
        <div>
          <p className="text-xs text-muted">Serious complaint, next 6 months</p>
          <p className="num text-2xl font-bold text-navy-ink">{fmtPct(w.forecast_probability)}</p>
          <p className="text-xs text-muted">range {fmtPct(w.forecast_interval[0])}–{fmtPct(w.forecast_interval[1])}, {humanize(w.forecast_status).toLowerCase()}, {humanize(w.forecast_confidence).toLowerCase()} confidence</p>
        </div>
        <div className="text-sm lg:text-right">
          <p><span className="num font-semibold">{w.open_cases}</span> open, <span className={`num font-semibold ${w.overdue_cases ? "text-red-ink" : ""}`}>{w.overdue_cases}</span> overdue</p>
          <p className="text-xs text-muted">Last activity {fmtDateTime(w.last_activity)}</p>
          <p className="text-xs font-semibold text-ink">Next review by {fmtDate(w.next_review)}</p>
          <p className="mt-2 flex gap-3 lg:justify-end">
            <Link to={`/institutions/${w.institution_id}`} className="text-sm font-semibold">Profile</Link>
            <a href={`/institutions/${w.institution_id}/dossier`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold">
              <LuFileText aria-hidden /> Dossier</a>
          </p>
        </div>
      </div>
    </li>
  );
}
