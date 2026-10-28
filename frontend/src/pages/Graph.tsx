import { useMemo, useState } from "react";
import type { GraphEdge, GraphGroup, GraphNode, GraphOut } from "../api/models";
import { ForceGraph } from "../components/forcegraph";
import { useTitle } from "../components/layout";
import { Card, Chip, Empty, ErrorState, KeyValues, Loading, PageHeader, RiskChip, SelectInput } from "../components/ui";
import { demoLabel, fmtNum, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, setQuery, useLocation } from "../lib/router";
import { C, RISK_COLOR } from "../lib/theme";

export function GraphPage() {
  useTitle("Trust / Society Graph");
  const { params } = useLocation();
  const hideStandalone = params.get("standalone") !== "show";
  const { data, error, loading, reload } = useApi<GraphOut>("/api/graph", { hide_standalone: hideStandalone });
  const focusTrust = params.get("trust");
  const [selected, setSelected] = useState<string | null>(focusTrust ? `T:${focusTrust}` : null);
  const nodes = (data?.nodes ?? []) as unknown as GraphNode[];
  const edges = (data?.edges ?? []) as unknown as GraphEdge[];
  const groups = (data?.groups ?? []) as unknown as GraphGroup[];
  const byKey = useMemo(() => new Map(nodes.map((n) => [n.key, n])), [nodes]);
  const sel = selected ? byKey.get(selected) ?? null : null;
  return (
    <div>
      <PageHeader title="Trust and society graph"
        subtitle="Institutions connected to the trust, society or management group that operates them. Links come only from stored relationship records, never from similar names."
        meta={data && <span className="text-xs text-muted">{data.provenance}</span>} />
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs font-semibold text-ink">Show
          <SelectInput className="mt-1 w-72 font-normal" value={hideStandalone ? "" : "show"} onChange={(v) => setQuery({ standalone: v || null })}
            options={[{ value: "", label: "Trusts and the institutions they run" }, { value: "show", label: "Also institutions without a recorded trust" }]} />
        </label>
        <label className="flex flex-col text-xs font-semibold text-ink">Find an institution or trust
          <SelectInput className="mt-1 w-80 font-normal" value={selected ?? ""} onChange={(v) => setSelected(v || null)} placeholder="Choose to highlight"
            options={[...nodes].sort((a, b) => (a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === "trust" ? -1 : 1))
              .map((n) => ({ value: n.key, label: `${n.kind === "trust" ? "Trust: " : ""}${n.label}` }))} />
        </label>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <div className="xl:col-span-8">
            <ForceGraph nodes={nodes} edges={edges} selected={selected} onSelect={setSelected} focusKey={focusTrust ? `T:${focusTrust}` : null} />
            <Legend legend={data.legend} stats={data.stats} />
          </div>
          <div className="space-y-4 xl:col-span-4">
            {sel ? <NodePanel n={sel} byKey={byKey} edges={edges} onSelect={setSelected} />
              : <Card title="Select a node"><p className="text-sm text-muted">Click a trust (square) or an institution (circle) to see linked institutions, open cases, risk and overlap signals. Drag nodes to rearrange; scroll or pinch to zoom.</p></Card>}
          </div>
          <Card className="xl:col-span-12" title="Group-level patterns" subtitle="Counts are computed from the case records of each trust’s institutions">
            {groups.length === 0 ? <Empty title="No trust relationships recorded" /> : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead><tr><th scope="col">Trust / society</th><th scope="col" className="num">Institutions</th><th scope="col" className="num">Flagged</th>
                    <th scope="col" className="num">Open cases</th><th scope="col" className="num">Overdue</th><th scope="col" className="num">Avg / max risk</th>
                    <th scope="col">States</th><th scope="col">Patterns</th></tr></thead>
                  <tbody>
                    {groups.map((g) => (
                      <tr key={g.trust_id}>
                        <td><button type="button" className="text-left font-semibold text-blue-ink hover:underline" onClick={() => setSelected(`T:${g.trust_id}`)}>{g.name}</button>
                          <span className="block text-xs text-muted">{g.provenance}</span></td>
                        <td className="num">{g.members}</td>
                        <td className={`num ${g.flagged_members >= 2 ? "font-bold text-red-ink" : ""}`}>{g.flagged_members}</td>
                        <td className="num">{fmtNum(g.open_cases)}</td>
                        <td className="num">{fmtNum(g.overdue)}</td>
                        <td className="num">{g.avg_risk ?? "—"} / {g.max_risk ?? "—"}</td>
                        <td className="text-xs">{g.states.join(", ")}</td>
                        <td>{g.patterns.length ? <ul className="flex flex-wrap gap-1">{g.patterns.map((p) => <li key={p}><Chip tone="orange">{p}</Chip></li>)}</ul> : <span className="text-muted">—</span>}</td>
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

function Legend({ legend, stats }: { legend: Record<string, string>; stats: Record<string, number> }) {
  return (
    <div className="mt-2 grid grid-cols-1 gap-2 rounded-md border border-line bg-white p-3 text-xs text-muted sm:grid-cols-2">
      <p className="flex items-center gap-2"><svg width="16" height="16" aria-hidden><rect x="2" y="2" width="12" height="12" rx="2" fill={C.navy} /></svg>{legend.trust}</p>
      <p className="flex items-center gap-2"><svg width="16" height="16" aria-hidden><circle cx="8" cy="8" r="6" fill={RISK_COLOR.HIGH} /></svg>
        <span>{legend.institution}: <span style={{ color: RISK_COLOR.HIGH }}>high</span>, <span style={{ color: "#C9690A" }}>elevated</span>, <span style={{ color: RISK_COLOR.NORMAL }}>normal</span></span></p>
      <p className="flex items-center gap-2"><svg width="24" height="10" aria-hidden><line x1="0" y1="5" x2="24" y2="5" stroke="#9AA8BE" strokeWidth="2" /></svg>{legend.OPERATED_BY}</p>
      <p className="flex items-center gap-2"><svg width="16" height="16" aria-hidden><circle cx="8" cy="8" r="6" fill="none" stroke={C.red} strokeWidth="2" /></svg>{legend.flagged}</p>
      <p className="sm:col-span-2">{stats.institutions} institutions, {stats.trusts} trusts, {stats.edges} relationships, {stats.standalone_institutions ?? 0} institutions shown without a trust.</p>
    </div>
  );
}

function NodePanel({ n, byKey, edges, onSelect }: { n: GraphNode; byKey: Map<string, GraphNode>; edges: GraphEdge[]; onSelect: (k: string) => void }) {
  if (n.kind === "trust") {
    const members = edges.filter((e) => e.source === n.key).map((e) => byKey.get(e.target)).filter((x): x is GraphNode => !!x);
    return (
      <Card title={n.label} subtitle={n.provenance}>
        <KeyValues items={[
          ["Institutions run", n.members ?? members.length], ["Flagged institutions", n.flagged_members ?? 0],
          ["Open cases", fmtNum(n.open_cases)], ["Overdue", fmtNum(n.overdue)],
          ["Average risk", n.avg_risk ?? "—"], ["Highest risk", n.max_risk ?? "—"],
        ]} />
        {n.patterns && n.patterns.length > 0 && <ul className="mt-3 flex flex-wrap gap-1">{n.patterns.map((p) => <li key={p}><Chip tone="orange">{p}</Chip></li>)}</ul>}
        <p className="mt-3 text-xs font-semibold text-ink">Institutions</p>
        <ul className="mt-1 space-y-1.5 text-sm">
          {members.sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0)).map((m) => (
            <li key={m.key} className="flex items-center justify-between gap-2">
              <button type="button" className="text-left text-blue-ink hover:underline" onClick={() => onSelect(m.key)}>{m.label}</button>
              <span className="flex shrink-0 items-center gap-1">{m.flagged && <Chip tone="red">flagged</Chip>}<RiskChip band={m.risk_band} score={m.risk} /></span>
            </li>
          ))}
        </ul>
      </Card>
    );
  }
  const trustEdge = edges.find((e) => e.target === n.key);
  const trust = trustEdge ? byKey.get(trustEdge.source) : undefined;
  return (
    <Card title={n.label} subtitle={`${n.district ? `${n.district}, ` : ""}${n.state}${n.synthetic ? ". Synthetic record" : ""}`}
      actions={<Link to={`/institutions/${n.id}`} className="text-sm font-semibold">Open profile</Link>}>
      <p className="mb-3 flex flex-wrap items-center gap-2"><RiskChip band={n.risk_band} score={n.risk} />
        {n.trend && <Chip tone={n.trend === "RISING" ? "red" : "neutral"}>{humanize(n.trend)}</Chip>}
        {n.demo_tag && <Chip tone="navy">Demo: {demoLabel(n.demo_tag)}</Chip>}</p>
      <KeyValues items={[
        ["Open cases", fmtNum(n.open_cases)], ["Overdue", fmtNum(n.overdue)], ["All cases", fmtNum(n.total_cases ?? 0)],
        ["Bureaus/Cells with open cases", n.open_bureaus ?? 0], ["Open overlap alerts", n.open_overlaps ?? 0], ["Open conflicts", n.conflicts ?? 0],
        ["Operated by", trust ? <button type="button" className="text-left text-blue-ink hover:underline" onClick={() => onSelect(trust.key)}>{trust.label}</button> : "No recorded trust"],
      ]} />
      {n.flag_reasons && n.flag_reasons.length > 0 && <p className="mt-3 text-sm">Flagged because: {n.flag_reasons.join(", ")}.</p>}
    </Card>
  );
}
