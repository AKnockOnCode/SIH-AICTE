import { useState } from "react";
import { LuDownload, LuFileSpreadsheet } from "react-icons/lu";
import { api, type Query } from "../api/client";
import type { ReportTable } from "../api/models";
import { HBars, Legend, TrendChart } from "../components/charts";
import { FilterBar, urlFilters } from "../components/filters";
import { useTitle } from "../components/layout";
import { Button, Card, Empty, ErrorState, Loading, PageHeader, SelectInput, Tabs } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct } from "../lib/format";
import { useApi } from "../lib/hooks";
import { setQuery, useLocation } from "../lib/router";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { C } from "../lib/theme";

const REPORTS = [
  { value: "summary", label: "Summary" },
  { value: "ageing", label: "Pending ageing" },
  { value: "performance", label: "Monthly / quarterly performance" },
  { value: "sla", label: "SLA compliance" },
  { value: "overlaps", label: "Overlaps and conflicts" },
] as const;
type ReportKey = (typeof REPORTS)[number]["value"];
const GROUPS = ["bureau", "region", "state", "institution", "category", "status", "month", "quarter"];
const isRate = (key: string) => /rate|compliance|share|ratio/.test(key);

export function ReportsPage() {
  useTitle("Reports & Analytics");
  const { params } = useLocation();
  const { can } = useSession();
  const toast = useToast();
  const report = (params.get("report") ?? "summary") as ReportKey;
  const groupBy = params.get("group_by") ?? "bureau";
  const period = params.get("period") ?? "month";
  const filters = urlFilters(params, ["dates", "bureau", "region", "state", "category", "status"]);
  const query: Query = { ...filters, group_by: report === "summary" || report === "ageing" ? groupBy : undefined, period: report === "performance" ? period : undefined };
  const { data, error, loading, reload } = useApi<ReportTable>(`/api/reports/${report}`, query);
  const [downloading, setDownloading] = useState<string | null>(null);
  const exportAs = async (fmt: "csv" | "xlsx") => {
    setDownloading(fmt);
    try {
      const name = await api.download("/api/reports/export", { ...query, report, fmt }, `agnidrishti-${report}.${fmt}`);
      toast.push(`Downloaded ${name}. The export carries the filters, generation time and synthetic-data notice.`);
    } catch (e) {
      toast.push((e as Error).message, "error");
    } finally {
      setDownloading(null);
    }
  };
  return (
    <div>
      <PageHeader title="Reports and analytics"
        subtitle="Live database aggregates with the filters applied below. Exports use exactly the same filters and contain no personal data."
        actions={can("report.export") && <>
          <Button icon={<LuDownload aria-hidden />} busy={downloading === "csv"} onClick={() => exportAs("csv")}>Export CSV</Button>
          <Button icon={<LuFileSpreadsheet aria-hidden />} busy={downloading === "xlsx"} onClick={() => exportAs("xlsx")}>Export Excel</Button>
        </>} />
      <Tabs value={report} onChange={(r) => setQuery({ report: r === "summary" ? null : r })} className="mb-3" tabs={REPORTS.map((r) => ({ value: r.value, label: r.label }))} />
      <FilterBar show={["dates", "bureau", "region", "state", "category", "status"]}>
        {(report === "summary" || report === "ageing") && (
          <label className="flex flex-col text-xs font-semibold text-ink">Group by
            <SelectInput className="mt-1 w-40 font-normal" value={groupBy} onChange={(v) => setQuery({ group_by: v === "bureau" ? null : v })}
              options={GROUPS.filter((g) => report === "summary" || !["month", "quarter", "status"].includes(g)).map((g) => ({ value: g, label: g.charAt(0).toUpperCase() + g.slice(1) }))} />
          </label>
        )}
        {report === "performance" && (
          <label className="flex flex-col text-xs font-semibold text-ink">Period
            <SelectInput className="mt-1 w-36 font-normal" value={period} onChange={(v) => setQuery({ period: v === "month" ? null : v })}
              options={[{ value: "month", label: "Monthly" }, { value: "quarter", label: "Quarterly" }]} />
          </label>
        )}
      </FilterBar>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && (
        <div className={loading ? "opacity-60" : ""}>
          {data.rows.length > 0 && report === "summary" && !["month", "quarter"].includes(groupBy) && (
            <Card className="mb-4" title="Open and overdue cases" subtitle={`Top ${Math.min(12, data.rows.length)} groups by open cases`}>
              <HBars ariaLabel="Open and overdue cases per group"
                rows={[...data.rows].sort((a, b) => Number(b.open_total) - Number(a.open_total)).slice(0, 12).map((r) => ({
                  key: String(r.key ?? r.group), label: <span title={String(r.group)}>{String(r.key ?? r.group).slice(0, 14)}</span>,
                  segments: [
                    { key: "late", value: Number(r.overdue), color: C.red, label: "Overdue" },
                    { key: "ontime", value: Math.max(0, Number(r.open_total) - Number(r.overdue)), color: C.blue, label: "Open, within SLA" },
                  ],
                }))} />
              <div className="mt-2"><Legend items={[{ label: "Overdue", color: C.red, shape: "bar" }, { label: "Open, within SLA", color: C.blue, shape: "bar" }]} /></div>
            </Card>
          )}
          {data.rows.length > 0 && (report === "performance" || (report === "summary" && ["month", "quarter"].includes(groupBy))) && (
            <Card className="mb-4" title="Received and disposed per period">
              <TrendChart points={data.rows.slice(-24).map((r) => ({ month: String(r.group).length === 7 ? String(r.group) : `${String(r.group).slice(0, 4)}-${String((Number(String(r.group).slice(-1)) || 1) * 3).padStart(2, "0")}`,
                received: Number(r.received), disposed: Number(r.disposed) }))} />
            </Card>
          )}
          <Card title={data.title} subtitle={`Generated ${fmtDateTime(data.generated_at)}. ${data.disclaimer}`}>
            {Object.keys(data.filters).length > 0 && (
              <p className="mb-2 text-xs text-muted">Filters: {Object.entries(data.filters).map(([k, v]) => `${k} = ${Array.isArray(v) ? v.join(", ") : String(v)}`).join("; ")}</p>
            )}
            {data.rows.length === 0 ? <Empty title="No cases match these filters" /> : (
              <div className="max-h-[640px] overflow-auto">
                <table className="data-table">
                  <thead><tr>{data.columns.map((c) => <th key={c.key} scope="col" className={c.key === "group" ? "min-w-56" : "num"}>{c.label}</th>)}</tr></thead>
                  <tbody>
                    {data.rows.map((r, i) => (
                      <tr key={i}>
                        {data.columns.map((c) => {
                          const v = r[c.key];
                          const text = v === null || v === undefined ? "—" : typeof v === "number" ? (isRate(c.key) ? fmtPct(v, 1) : fmtNum(v)) : String(v);
                          return <td key={c.key} className={c.key === "group" ? "font-medium" : "num"}>{text}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
