import type { InstitutionPage } from "../api/models";
import { UrlTextInput } from "../components/cases";
import { useTitle } from "../components/layout";
import { BureauTag, Card, Chip, Empty, ErrorState, Loading, MultiSelect, PageHeader, Pagination, RiskChip, SelectInput } from "../components/ui";
import { demoLabel, fmtNum, fmtPct, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useRefData } from "../lib/session";

export function InstitutionsPage() {
  useTitle("Institution Master");
  const { params } = useLocation();
  const ref = useRefData();
  const page = Number(params.get("page") ?? "1") || 1;
  const query = {
    page, page_size: 25, q: params.get("q") || undefined, region: listParam(params, "region"), state: listParam(params, "state"),
    trust_id: params.get("trust_id") || undefined, risk_band: listParam(params, "risk_band"), sort: params.get("sort") || "risk_desc",
  };
  const { data, error, loading, reload } = useApi<InstitutionPage>("/api/institutions", query);
  return (
    <div>
      <PageHeader title="Institution Master"
        subtitle="One canonical record per institution, with aliases, Permanent ID and trust. Every complaint from every Bureau/Cell is linked here through entity resolution." />
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
        <UrlTextInput param="q" label="Name, alias or Permanent ID" placeholder="Fuzzy: e.g. SIET Bhopal" className="w-full sm:w-72" />
        <MultiSelect label="Region" className="w-full sm:w-48" value={query.region} onChange={(v) => setQuery({ region: v, page: null })}
          options={ref.regions.map((r) => ({ value: r.code, label: r.name }))} />
        <MultiSelect label="State" className="w-full sm:w-48" value={query.state} onChange={(v) => setQuery({ state: v, page: null })}
          options={ref.states.map((s) => ({ value: s.name, label: s.name }))} />
        <MultiSelect label="Risk band" className="w-full sm:w-44" value={query.risk_band} onChange={(v) => setQuery({ risk_band: v, page: null })}
          options={["HIGH", "ELEVATED", "NORMAL"].map((b) => ({ value: b, label: humanize(b) }))} />
        <label className="flex flex-col text-xs font-semibold text-ink">Trust / society
          <SelectInput className="mt-1 w-56 font-normal" value={query.trust_id ?? ""} onChange={(v) => setQuery({ trust_id: v || null, page: null })} placeholder="Any"
            options={ref.trusts.map((t) => ({ value: t.id, label: t.name }))} /></label>
        <label className="flex flex-col text-xs font-semibold text-ink">Sort
          <SelectInput className="mt-1 w-44 font-normal" value={query.sort} onChange={(v) => setQuery({ sort: v === "risk_desc" ? null : v, page: null })}
            options={[{ value: "risk_desc", label: "Highest risk" }, { value: "open_desc", label: "Most open cases" }, { value: "overdue_desc", label: "Most overdue" }, { value: "name", label: "Name" }]} /></label>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && data.total === 0 && <Empty title="No institution matches">Try a shorter name or an abbreviation.</Empty>}
      {data && data.total > 0 && (
        <Card title={`${fmtNum(data.total)} institution${data.total === 1 ? "" : "s"}`}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th scope="col">Institution</th><th scope="col">Location</th><th scope="col">Trust / society</th><th scope="col" className="num">Cases</th>
                <th scope="col" className="num">Open</th><th scope="col" className="num">Overdue</th><th scope="col">Open with</th><th scope="col">Risk</th><th scope="col" className="num">Overlaps</th></tr></thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id}>
                    <td className="min-w-56"><Link to={`/institutions/${i.id}`} className="font-semibold">{i.name}</Link>
                      <span className="block text-xs text-muted">{i.permanent_id ?? "No Permanent ID"}{i.is_synthetic ? ", synthetic" : ", imported"}</span>
                      {i.match_confidence !== null && <Chip tone={i.match_band === "HIGH" ? "green" : "orange"}>match {fmtPct(i.match_confidence)}</Chip>}
                      {i.demo_tag && <Chip tone="navy">{demoLabel(i.demo_tag)}</Chip>}</td>
                    <td className="text-xs">{i.district ? `${i.district}, ` : ""}{i.state}<span className="block text-muted">{ref.regionName(i.region_code)}</span></td>
                    <td className="text-xs">{i.trust_id ? <Link to={`/graph?trust=${i.trust_id}`}>{i.trust_name}</Link> : "—"}</td>
                    <td className="num">{fmtNum(i.total_cases)}</td>
                    <td className="num">{fmtNum(i.open_cases)}</td>
                    <td className={`num ${i.overdue_cases ? "font-semibold text-red-ink" : ""}`}>{fmtNum(i.overdue_cases)}</td>
                    <td><span className="flex flex-wrap gap-1.5">{i.open_bureaus.map((b) => <BureauTag key={b} code={b} />)}</span></td>
                    <td><RiskChip band={i.risk_band} score={i.risk_score} />{i.risk_trend === "RISING" && <span className="block text-xs text-red-ink">rising</span>}</td>
                    <td className="num">{i.open_overlaps ? <Link to={`/institutions/${i.id}`}>{i.open_overlaps}</Link> : 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={25} total={data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />
        </Card>
      )}
    </div>
  );
}
