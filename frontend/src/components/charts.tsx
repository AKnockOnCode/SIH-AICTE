// Lightweight SVG/HTML charts drawn with d3 scales/shapes (no hosted chart services).
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { max as d3max } from "d3-array";
import { sankey, sankeyLinkHorizontal } from "d3-sankey";
import { scaleBand, scaleLinear } from "d3-scale";
import { arc, line, pie } from "d3-shape";
import { fmtMonth, fmtNum, fmtPct } from "../lib/format";
import { Link } from "../lib/router";
import { BAND_COLOR, C } from "../lib/theme";

export function useElementWidth<T extends HTMLElement>(fallback = 600): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => setWidth(Math.max(240, Math.floor(el.getBoundingClientRect().width)));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function Legend({ items }: { items: Array<{ label: string; color: string; shape?: "dot" | "bar" | "line" }> }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span aria-hidden className={i.shape === "line" ? "inline-block h-0.5 w-4" : i.shape === "bar" ? "inline-block h-2.5 w-3 rounded-sm"
            : "inline-block h-2.5 w-2.5 rounded-full"} style={{ background: i.color }} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

// ----------------------------------------------------------------------------- horizontal stacked bars (HTML)
export interface BarRow {
  key: string;
  label: ReactNode;
  segments: Array<{ key: string; value: number; color: string; label: string }>;
  right?: ReactNode;
  to?: string;
}

export function HBars({ rows, maxValue, ariaLabel }: { rows: BarRow[]; maxValue?: number; ariaLabel: string }) {
  const top = maxValue ?? Math.max(1, ...rows.map((r) => r.segments.reduce((s, x) => s + x.value, 0)));
  return (
    <ul className="space-y-2.5" aria-label={ariaLabel}>
      {rows.map((r) => {
        const total = r.segments.reduce((s, x) => s + x.value, 0);
        const title = r.segments.map((s) => `${s.label}: ${fmtNum(s.value)}`).join(", ");
        const bar = (
          <div className="flex h-5 w-full overflow-hidden rounded bg-slate-soft" title={title} role="img"
            aria-label={`${typeof r.label === "string" ? r.label : r.key}: ${title}`}>
            {r.segments.filter((s) => s.value > 0).map((s) => (
              <div key={s.key} style={{ width: `${(s.value / top) * 100}%`, background: s.color }} className="h-full" />
            ))}
          </div>
        );
        return (
          <li key={r.key} className="grid grid-cols-[minmax(64px,92px)_1fr_auto] items-center gap-3 text-sm">
            <span className="truncate font-medium text-ink">{r.label}</span>
            {r.to ? <Link to={r.to} className="block" aria-label={`Open cases for ${r.key}`}>{bar}</Link> : bar}
            <span className="num min-w-12 text-right text-xs text-muted">{r.right ?? fmtNum(total)}</span>
          </li>
        );
      })}
    </ul>
  );
}

// ----------------------------------------------------------------------------- donut
export function Donut({ data, center, size = 168 }: { data: Array<{ key: string; label: string; value: number; color: string }>;
  center: ReactNode; size?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2;
  const arcs = pie<{ value: number }>().sort(null).value((d) => d.value)(data);
  const gen = arc<{ startAngle: number; endAngle: number }>().innerRadius(r * 0.58).outerRadius(r - 2).padAngle(0.012);
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`${-r} ${-r} ${size} ${size}`} role="img"
        aria-label={data.map((d) => `${d.label} ${d.value}`).join(", ")}>
        {total === 0 ? <circle r={r - 2} fill="none" stroke={C.line} strokeWidth={r * 0.4} />
          : arcs.map((a, i) => <path key={data[i].key} d={gen(a) ?? ""} fill={data[i].color}><title>{`${data[i].label}: ${fmtNum(data[i].value)}`}</title></path>)}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">{center}</div>
    </div>
  );
}

// ----------------------------------------------------------------------------- trend
export function TrendChart({ points, height = 220 }: { points: Array<{ month: string; received: number; disposed: number }>; height?: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const m = { t: 12, r: 12, b: 28, l: 36 };
  const w = width - m.l - m.r;
  const h = height - m.t - m.b;
  const x = scaleBand<string>().domain(points.map((p) => p.month)).range([0, w]).padding(0.28);
  const top = d3max(points, (p) => Math.max(p.received, p.disposed)) ?? 1;
  const y = scaleLinear().domain([0, Math.max(1, top)]).nice().range([h, 0]);
  const path = line<{ month: string; disposed: number }>().x((p) => (x(p.month) ?? 0) + x.bandwidth() / 2).y((p) => y(p.disposed))(points) ?? "";
  const every = Math.ceil(points.length / Math.max(1, Math.floor(w / 46)));
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Cases received per month (bars) and disposed per month (line)">
        <g transform={`translate(${m.l},${m.t})`}>
          {y.ticks(4).map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line x1={0} x2={w} stroke="#E8EDF5" />
              <text x={-6} dy="0.32em" textAnchor="end" fontSize={11} fill={C.muted}>{t}</text>
            </g>
          ))}
          {points.map((p) => (
            <rect key={p.month} x={x(p.month)} y={y(p.received)} width={x.bandwidth()} height={h - y(p.received)} fill="#9CC3E6" rx={2}>
              <title>{`${fmtMonth(p.month)}: ${p.received} received, ${p.disposed} disposed`}</title>
            </rect>
          ))}
          <path d={path} fill="none" stroke={C.green} strokeWidth={2} />
          {points.map((p) => (
            <circle key={p.month} cx={(x(p.month) ?? 0) + x.bandwidth() / 2} cy={y(p.disposed)} r={2.8} fill={C.green} />
          ))}
          {points.map((p, i) => (i % every === 0 ? (
            <text key={p.month} x={(x(p.month) ?? 0) + x.bandwidth() / 2} y={h + 18} textAnchor="middle" fontSize={11} fill={C.muted}>
              {fmtMonth(p.month)}
            </text>
          ) : null))}
        </g>
      </svg>
    </div>
  );
}

// ----------------------------------------------------------------------------- vertical stacked bars
export function StackedColumns({ columns, series, height = 220, ariaLabel }: {
  columns: Array<{ key: string; label: string; values: Record<string, number> }>;
  series: Array<{ key: string; label: string; color: string }>; height?: number; ariaLabel: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const m = { t: 14, r: 8, b: 32, l: 36 };
  const w = width - m.l - m.r;
  const h = height - m.t - m.b;
  const x = scaleBand<string>().domain(columns.map((c) => c.key)).range([0, w]).padding(0.3);
  const totals = columns.map((c) => series.reduce((s, k) => s + (c.values[k.key] ?? 0), 0));
  const y = scaleLinear().domain([0, Math.max(1, ...totals)]).nice().range([h, 0]);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        <g transform={`translate(${m.l},${m.t})`}>
          {y.ticks(4).map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line x1={0} x2={w} stroke="#E8EDF5" />
              <text x={-6} dy="0.32em" textAnchor="end" fontSize={11} fill={C.muted}>{t}</text>
            </g>
          ))}
          {columns.map((c, ci) => {
            let acc = 0;
            return (
              <g key={c.key} transform={`translate(${x(c.key) ?? 0},0)`}>
                {series.map((s) => {
                  const v = c.values[s.key] ?? 0;
                  if (!v) return null;
                  const y0 = y(acc);
                  acc += v;
                  return (
                    <rect key={s.key} x={0} y={y(acc)} width={x.bandwidth()} height={y0 - y(acc)} fill={s.color}>
                      <title>{`${c.label}, ${s.label}: ${v}`}</title>
                    </rect>
                  );
                })}
                <text x={x.bandwidth() / 2} y={y(totals[ci]) - 4} textAnchor="middle" fontSize={11} fontWeight={600} fill={C.ink}>
                  {totals[ci] || ""}
                </text>
                <text x={x.bandwidth() / 2} y={h + 16} textAnchor="middle" fontSize={11} fill={C.muted}>{c.label}</text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

// ----------------------------------------------------------------------------- lollipop (PPT: complaint history by severity)
export function Lollipop({ points, height = 200 }: { points: Array<{ year: string; max_severity: number; cases: number; serious: number }>;
  height?: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const m = { t: 16, r: 16, b: 28, l: 34 };
  const w = width - m.l - m.r;
  const h = height - m.t - m.b;
  const x = scaleBand<string>().domain(points.map((p) => p.year)).range([0, w]).padding(0.5);
  const y = scaleLinear().domain([0, 5]).range([h, 0]);
  const color = (s: number) => (s >= 4 ? C.red : s === 3 ? C.orange : C.blue);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Complaint history by year: highest severity per year">
        <g transform={`translate(${m.l},${m.t})`}>
          {[1, 2, 3, 4, 5].map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line x1={0} x2={w} stroke="#EEF2F8" />
              <text x={-8} dy="0.32em" textAnchor="end" fontSize={10} fill={C.muted}>S{t}</text>
            </g>
          ))}
          {points.map((p) => {
            const cx = (x(p.year) ?? 0) + x.bandwidth() / 2;
            return (
              <g key={p.year}>
                <line x1={cx} x2={cx} y1={h} y2={y(p.max_severity)} stroke={C.slate} strokeWidth={1.5} />
                <circle cx={cx} cy={y(p.max_severity)} r={6 + Math.min(8, p.cases)} fill={color(p.max_severity)} opacity={0.92}>
                  <title>{`${p.year}: ${p.cases} case(s), highest severity ${p.max_severity}/5, ${p.serious} serious`}</title>
                </circle>
                <text x={cx} y={y(p.max_severity) + 4} textAnchor="middle" fontSize={10} fontWeight={700} fill="#fff">{p.cases}</text>
                <text x={cx} y={h + 18} textAnchor="middle" fontSize={11} fill={C.muted}>{p.year}</text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

// ----------------------------------------------------------------------------- risk gauge (PPT semicircle)
export function Gauge({ value, color, size = 170, label }: { value: number; color: string; size?: number; label?: string }) {
  const r = size / 2;
  const angle = (v: number) => -Math.PI / 2 + (Math.max(0, Math.min(100, v)) / 100) * Math.PI;
  const track = arc()({ innerRadius: r * 0.62, outerRadius: r - 2, startAngle: -Math.PI / 2, endAngle: Math.PI / 2 }) ?? "";
  const fill = arc()({ innerRadius: r * 0.62, outerRadius: r - 2, startAngle: -Math.PI / 2, endAngle: angle(value) }) ?? "";
  return (
    <svg width={size} height={r + 6} viewBox={`${-r} ${-r} ${size} ${r + 6}`} role="img" aria-label={`${label ?? "Score"} ${value.toFixed(0)} out of 100`}>
      <path d={track} fill="#E6EAF1" />
      <path d={fill} fill={color} />
      <text y={-4} textAnchor="middle" fontSize={r * 0.42} fontWeight={700} fill={color}>{value.toFixed(0)}</text>
    </svg>
  );
}

// ----------------------------------------------------------------------------- SLA bar (PPT)
export function SlaBar({ pct, state, label }: { pct: number; state: string; label: string }) {
  const color = state === "OVERDUE" ? C.red : state === "DUE_SOON" || pct >= 60 ? C.orange : C.blue;
  return (
    <div>
      <div className="h-4 w-full overflow-hidden rounded-md bg-[#E3E8F1]" role="progressbar" aria-valuenow={Math.min(100, pct)}
        aria-valuemin={0} aria-valuemax={100} aria-label="Share of SLA time used">
        <div className="h-full rounded-md" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
      </div>
      <p className="mt-2 text-sm text-muted">{Math.round(pct)}% of time used. {label}</p>
    </div>
  );
}

// ----------------------------------------------------------------------------- intake triage sankey (PPT)
type SNode = { id: string; label: string; color: string };
type SLink = { source: string; target: string; value: number };

export function TriageSankey({ groups, flows, received, height = 260 }: {
  groups: Array<{ key: string; label: string; n: number }>; flows: Array<{ group: string; band: string; n: number }>;
  received: number; height?: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const groupColor: Record<string, string> = { DUPLICATE: C.green, RELATED: C.orange, UNIQUE: C.blue };
  const bands = ["CRITICAL", "HIGH", "MEDIUM", "LOW"].filter((b) => flows.some((f) => f.band === b && f.n > 0));
  const nodes: SNode[] = [
    { id: "RECEIVED", label: `Received ${fmtNum(received)}`, color: C.navy },
    ...groups.filter((g) => g.n > 0).map((g) => ({ id: g.key, label: `${g.label} ${fmtNum(g.n)}`, color: groupColor[g.key] ?? C.slate })),
    ...bands.map((b) => ({ id: b, label: `${b.charAt(0)}${b.slice(1).toLowerCase()} ${fmtNum(flows.filter((f) => f.band === b).reduce((s, f) => s + f.n, 0))}`,
      color: BAND_COLOR[b] })),
  ];
  const links: SLink[] = [
    ...groups.filter((g) => g.n > 0).map((g) => ({ source: "RECEIVED", target: g.key, value: g.n })),
    ...flows.filter((f) => f.n > 0).map((f) => ({ source: f.group, target: f.band, value: f.n })),
  ];
  const labelSpace = Math.min(150, width * 0.3);
  if (received === 0) return <p className="py-6 text-sm text-muted">No cases in the selected period.</p>;
  const layout = sankey<SNode, SLink>().nodeId((d) => d.id).nodeWidth(12).nodePadding(14).nodeSort(null)
    .extent([[1, 6], [width - labelSpace, height - 6]]);
  const graph = layout({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) });
  const path = sankeyLinkHorizontal();
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img"
        aria-label={`Intake triage: ${groups.map((g) => `${g.label} ${g.n}`).join(", ")}; by priority band`}>
        <g fill="none">
          {graph.links.map((l, i) => {
            const src = l.source as SNode & { x0?: number };
            return (
              <path key={i} d={path(l) ?? ""} stroke={src.id === "RECEIVED" ? (l.target as SNode).color : src.color}
                strokeOpacity={0.28} strokeWidth={Math.max(1, l.width ?? 1)}>
                <title>{`${(l.source as SNode).label.replace(/ [\d,]+$/, "")} → ${(l.target as SNode).label.replace(/ [\d,]+$/, "")}: ${l.value}`}</title>
              </path>
            );
          })}
        </g>
        {graph.nodes.map((n) => (
          <g key={n.id}>
            <rect x={n.x0} y={n.y0} width={(n.x1 ?? 0) - (n.x0 ?? 0)} height={Math.max(1, (n.y1 ?? 0) - (n.y0 ?? 0))} fill={n.color} />
            <text x={(n.x1 ?? 0) + 6} y={((n.y0 ?? 0) + (n.y1 ?? 0)) / 2} dy="0.35em" fontSize={12} fontWeight={600} fill={C.ink}
              stroke="#fff" strokeWidth={4} strokeLinejoin="round" paintOrder="stroke">
              {n.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function PctBar({ value, color = C.blue }: { value: number | null | undefined; color?: string }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="inline-block h-1.5 w-14 overflow-hidden rounded-full bg-slate-soft">
        <span className="block h-full rounded-full" style={{ width: `${Math.min(100, value * 100)}%`, background: color }} />
      </span>
      <span className="num">{fmtPct(value)}</span>
    </span>
  );
}
