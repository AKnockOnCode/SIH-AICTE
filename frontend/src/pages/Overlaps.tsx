import { useState } from "react";
import { LuRefreshCw, LuShieldAlert } from "react-icons/lu";
import { api } from "../api/client";
import type { OverlapPage, OverlapRow } from "../api/models";
import { UrlTextInput } from "../components/cases";
import { useTitle } from "../components/layout";
import { BureauTag, Button, Card, Chip, Empty, ErrorState, Loading, PageHeader, Pagination, SelectInput, Tabs, TierChip } from "../components/ui";
import { fmtDateTime, fmtNum, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

const TIERS = ["CONFLICT", "DUPLICATE", "RELATED"] as const;
const TIER_HELP: Record<string, string> = {
  CONFLICT: "A favourable regulatory action meets a serious open (or recently substantiated) complaint in another Bureau/Cell.",
  DUPLICATE: "The same grievance registered more than once: merge into a Master Case without losing either record.",
  RELATED: "Same institution and issue family: link for context so each Bureau/Cell sees the other's file.",
};

export function OverlapsPage() {
  useTitle("Overlap & Conflict Alerts");
  const { params } = useLocation();
  const ref = useRefData();
  const { can, bump } = useSession();
  const toast = useToast();
  const [scanning, setScanning] = useState(false);
  const tier = params.get("tier") ?? "CONFLICT";
  const statuses = listParam(params, "status");
  const page = Number(params.get("page") ?? "1") || 1;
  const query = {
    tier: [tier], status: statuses.length ? statuses : ["OPEN", "UNDER_REVIEW"], q: params.get("q") || undefined,
    bureau: params.get("bureau") || undefined, cross_bureau: params.get("cross_bureau") === "true" ? true : undefined, page, page_size: 25,
  };
  const { data, error, loading, reload } = useApi<OverlapPage>("/api/overlaps", query);
  const openCount = (t: string) => {
    const c = data?.counts[t];
    return c ? (c.OPEN ?? 0) + (c.UNDER_REVIEW ?? 0) : undefined;
  };
  return (
    <div>
      <PageHeader title="Overlap and conflict alerts"
        subtitle="Cases about the same institution handled by different Bureaus/Cells, grouped by tier. Open an alert to compare the cases side by side and coordinate."
        actions={can("system.sweep") && <Button size="sm" icon={<LuRefreshCw aria-hidden />} busy={scanning} onClick={async () => {
          setScanning(true);
          try {
            const r = await api.post<{ triggers: number; created: number; updated: number }>("/api/overlaps/scan");
            toast.push(`Re-scan complete: ${r.created} new alert(s); existing alerts re-checked ${r.updated} time(s) across ${r.triggers} open or recently acted-on cases.`, "info");
            bump();
          } catch (e) {
            toast.push((e as Error).message, "error");
          } finally {
            setScanning(false);
          }
        }}>Re-scan all open cases</Button>} />
      <Tabs value={tier} onChange={(t) => setQuery({ tier: t === "CONFLICT" ? null : t, page: null })} className="mb-3"
        tabs={TIERS.map((t) => ({ value: t, label: humanize(t), count: openCount(t) }))} />
      <p className="mb-3 flex items-start gap-2 text-sm text-muted"><LuShieldAlert aria-hidden className="mt-0.5 shrink-0" />{TIER_HELP[tier]}</p>
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
        <UrlTextInput param="q" label="Search" placeholder="Institution, alert ID or case ID" className="w-full sm:w-72" />
        <label className="flex flex-col text-xs font-semibold text-ink">
          Status
          <SelectInput className="mt-1 w-48 font-normal" value={statuses.join(",")} onChange={(v) => setQuery({ status: v || null, page: null })}
            placeholder="Open and under review"
            options={[{ value: "OPEN", label: "Open" }, { value: "UNDER_REVIEW", label: "Under review" }, { value: "RESOLVED", label: "Resolved" },
              { value: "DISMISSED", label: "Dismissed" }, { value: "OPEN,UNDER_REVIEW,RESOLVED,DISMISSED", label: "All statuses" }]} />
        </label>
        <label className="flex flex-col text-xs font-semibold text-ink">
          Bureau/Cell involved
          <SelectInput className="mt-1 w-44 font-normal" value={params.get("bureau") ?? ""} onChange={(v) => setQuery({ bureau: v || null, page: null })}
            placeholder="Any" options={ref.bureaus.map((b) => ({ value: b.code, label: b.code }))} />
        </label>
        <label className="flex items-center gap-1.5 pb-2 text-sm">
          <input type="checkbox" checked={params.get("cross_bureau") === "true"} onChange={(e) => setQuery({ cross_bureau: e.target.checked ? "true" : null, page: null })} />
          Across Bureaus/Cells only
        </label>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && data.total === 0 && <Empty title={`No ${humanize(tier).toLowerCase()} alerts match`}>Try another status or clear the search.</Empty>}
      {data && data.total > 0 && (
        <Card title={`${fmtNum(data.total)} ${humanize(tier).toLowerCase()} alert${data.total === 1 ? "" : "s"}`}>
          <ul className="divide-y divide-line">
            {data.items.map((o) => <OverlapItem key={o.id} o={o} />)}
          </ul>
          <Pagination page={page} pageSize={25} total={data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />
        </Card>
      )}
    </div>
  );
}

function OverlapItem({ o }: { o: OverlapRow }) {
  return (
    <li className="py-3">
      <Link to={`/overlaps/${o.id}`} className="group grid grid-cols-1 gap-2 no-underline md:grid-cols-[1fr_auto]">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <TierChip tier={o.tier} />
            <span className={`font-semibold group-hover:underline ${o.tier === "CONFLICT" ? "text-red-ink" : "text-ink"}`}>{o.headline}</span>
            {o.demo_tag === "INSTITUTION_A" && <Chip tone="navy">Institution A demo</Chip>}
          </p>
          <p className="mt-1 text-sm text-ink">{o.institution_name} <span className="text-xs text-muted">({o.id}, score {o.score.toFixed(2)}, rules {o.rules.join(", ")})</span></p>
          <p className="mt-1 text-xs text-muted">Cases {o.cases.join(", ")}. Detected {fmtDateTime(o.created_at)}{o.trigger_type === "ACTION_ADDED" && o.trigger_case_id ? ` when an action was recorded on ${o.trigger_case_id}` : ""}.</p>
          {o.next_step && <p className="mt-1 text-xs text-ink">Next step: {o.next_step}</p>}
        </div>
        <div className="flex flex-wrap items-start gap-2 md:flex-col md:items-end">
          <span className="flex gap-2">{o.bureaus.map((b) => <BureauTag key={b} code={b} />)}</span>
          <Chip tone={o.status === "OPEN" ? "orange" : o.status === "UNDER_REVIEW" ? "blue" : "neutral"}>{humanize(o.status)}</Chip>
          {o.decided_lead ? <Chip tone="green">Lead {o.decided_lead} (agreed)</Chip> : o.recommended_lead ? <Chip tone="navy">Suggested lead {o.recommended_lead}</Chip> : null}
        </div>
      </Link>
    </li>
  );
}
