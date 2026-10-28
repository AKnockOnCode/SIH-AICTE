// Interactive force-directed trust/society graph (d3-force layout, d3-zoom pan/zoom, drag to pin).
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import type { GraphEdge, GraphNode } from "../api/models";
import { C, RISK_COLOR } from "../lib/theme";

type SimNode = GraphNode & SimulationNodeDatum;
type SimLink = SimulationLinkDatum<SimNode> & { relation: string };

export const nodeRadius = (n: GraphNode) => (n.kind === "trust" ? 11 + Math.min(10, (n.members ?? 1) * 1.4) : 5 + Math.min(13, Math.sqrt(n.open_cases) * 2.6));
export const nodeColor = (n: GraphNode) => (n.kind === "trust" ? C.navy : RISK_COLOR[n.risk_band ?? ""] ?? C.slate);

export function ForceGraph({ nodes, edges, selected, onSelect, height = 560, focusKey }: {
  nodes: GraphNode[]; edges: GraphEdge[]; selected: string | null; onSelect: (key: string | null) => void; height?: number; focusKey?: string | null }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [width, setWidth] = useState(900);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [, setFrame] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const drag = useRef<{ key: string; moved: boolean } | null>(null);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const sim = useMemo(() => {
    const simNodes: SimNode[] = nodes.map((n, i) => ({ ...n, x: Math.cos(i) * 200, y: Math.sin(i) * 200 }));
    const simLinks: SimLink[] = edges.map((e) => ({ source: e.source, target: e.target, relation: e.relation }));
    return { simNodes, simLinks, byKey: new Map(simNodes.map((n) => [n.key, n])) };
  }, [nodes, edges]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setWidth(Math.max(320, el.getBoundingClientRect().width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const s = forceSimulation<SimNode, SimLink>(sim.simNodes)
      .force("link", forceLink<SimNode, SimLink>(sim.simLinks).id((d) => d.key).distance((l) => 28 + nodeRadius(l.target as SimNode) * 2).strength(0.8))
      .force("charge", forceManyBody<SimNode>().strength((d) => (d.kind === "trust" ? -260 : -55)))
      .force("collide", forceCollide<SimNode>((d) => nodeRadius(d) + 3))
      .force("x", forceX<SimNode>(0).strength(0.045))
      .force("y", forceY<SimNode>(0).strength(0.07));
    simRef.current = s;
    if (reduced) {
      s.stop();
      for (let i = 0; i < 320; i++) s.tick();
      setFrame((f) => f + 1);
    } else {
      let raf = 0;
      s.on("tick", () => {
        if (!raf) raf = requestAnimationFrame(() => {
          raf = 0;
          setFrame((f) => f + 1);
        });
      });
    }
    return () => {
      s.stop();
    };
  }, [sim, reduced]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const z = zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 5])
      .filter((event: Event) => !(event.target as Element).closest?.("[data-node]") && (event.type !== "mousedown" || (event as MouseEvent).button === 0))
      .on("zoom", (event: { transform: ZoomTransform }) => setTransform(event.transform));
    zoomRef.current = z;
    select(svg).call(z);
    return () => {
      select(svg).on(".zoom", null);
    };
  }, []);

  // The graph origin sits at the centre of the canvas; re-centre when the canvas width changes.
  const home = () => zoomIdentity.translate(width / 2, height / 2).scale(width < 640 ? 0.7 : 1);
  useEffect(() => {
    if (svgRef.current && zoomRef.current) select(svgRef.current).call(zoomRef.current.transform, home());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  // Centre on a focused node (e.g. arriving from an institution's trust link).
  useEffect(() => {
    if (!focusKey || !svgRef.current || !zoomRef.current) return undefined;
    const t = window.setTimeout(() => {
      const n = sim.byKey.get(focusKey);
      if (!n || n.x === undefined || n.y === undefined || !svgRef.current || !zoomRef.current) return;
      select(svgRef.current).call(zoomRef.current.transform, zoomIdentity.translate(width / 2 - n.x * 1.6, height / 2 - n.y * 1.6).scale(1.6));
    }, reduced ? 50 : 1400);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, sim, reduced]);

  const toGraph = (e: ReactPointerEvent<SVGElement>): [number, number] => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return transform.invert([p.x, p.y]);
  };

  const neighbours = useMemo(() => {
    const focus = hover ?? selected;
    if (!focus) return null;
    const set = new Set([focus]);
    for (const l of sim.simLinks) {
      const s = (l.source as SimNode).key ?? (l.source as string);
      const t = (l.target as SimNode).key ?? (l.target as string);
      if (s === focus) set.add(t);
      if (t === focus) set.add(s);
    }
    return set;
  }, [hover, selected, sim]);

  return (
    <div ref={wrapRef} className="relative w-full overflow-hidden rounded-md border border-line bg-[#fbfcfe]">
      <svg ref={svgRef} width={width} height={height} role="img" aria-label="Trust and society relationship graph" className="cursor-grab touch-none active:cursor-grabbing"
        onPointerMove={(e) => {
          if (!drag.current) return;
          const n = sim.byKey.get(drag.current.key);
          if (!n) return;
          const [x, y] = toGraph(e);
          n.fx = x;
          n.fy = y;
          drag.current.moved = true;
          simRef.current?.alphaTarget(0.25).restart();
        }}
        onPointerUp={() => {
          if (drag.current && !drag.current.moved) onSelect(drag.current.key === selected ? null : drag.current.key);
          drag.current = null;
          simRef.current?.alphaTarget(0);
        }}
        onClick={(e) => {
          if (e.target === svgRef.current) onSelect(null);
        }}>
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {sim.simLinks.map((l, i) => {
            const s = l.source as SimNode;
            const t = l.target as SimNode;
            const dim = neighbours && !(neighbours.has(s.key) && neighbours.has(t.key));
            return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke={dim ? "#E3E8F0" : "#9AA8BE"} strokeWidth={dim ? 1 : 1.6} />;
          })}
          {sim.simNodes.map((n) => {
            const r = nodeRadius(n);
            const dim = neighbours && !neighbours.has(n.key);
            const isSel = selected === n.key;
            return (
              <g key={n.key} data-node transform={`translate(${n.x ?? 0},${n.y ?? 0})`} opacity={dim ? 0.28 : 1} className="cursor-pointer"
                tabIndex={0} role="button" aria-label={`${n.kind === "trust" ? "Trust" : "Institution"}: ${n.label}`}
                onPointerDown={(e) => {
                  (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
                  drag.current = { key: n.key, moved: false };
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(n.key);
                  }
                }}
                onMouseEnter={() => setHover(n.key)} onMouseLeave={() => setHover(null)}>
                {n.kind === "trust" ? (
                  <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={4} fill={C.navy} stroke={n.flagged ? C.red : "#fff"} strokeWidth={n.flagged ? 3 : 1.5} />
                ) : (
                  <>
                    {n.flagged && <circle r={r + 3.5} fill="none" stroke={C.red} strokeWidth={2} />}
                    <circle r={r} fill={nodeColor(n)} stroke="#fff" strokeWidth={1.5} />
                  </>
                )}
                {isSel && <circle r={r + 8} fill="none" stroke={C.blue} strokeWidth={2} strokeDasharray="4 3" />}
                {(n.kind === "trust" || isSel || hover === n.key || n.demo_tag === "INSTITUTION_A" || (neighbours?.has(n.key) ?? false)) && (
                  <text y={-r - 6 / transform.k} textAnchor="middle" fontSize={(n.kind === "trust" ? 12.5 : 11) / Math.max(0.6, transform.k)}
                    fontWeight={n.kind === "trust" ? 700 : 600} fill={C.ink} stroke="#fff" strokeWidth={3 / Math.max(0.6, transform.k)}
                    paintOrder="stroke" pointerEvents="none">
                    {n.label.length > 34 ? `${n.label.slice(0, 32)}…` : n.label}
                  </text>
                )}
                <title>{n.kind === "trust" ? `${n.label}: ${n.members} institutions, ${n.flagged_members} flagged`
                  : `${n.label}: risk ${n.risk?.toFixed(0) ?? "—"}, ${n.open_cases} open cases`}</title>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="absolute right-2 bottom-2 flex gap-1 print:hidden">
        {[["+", 1.4], ["−", 1 / 1.4]].map(([label, k]) => (
          <button key={label as string} type="button" aria-label={label === "+" ? "Zoom in" : "Zoom out"}
            className="h-8 w-8 rounded border border-line bg-white text-lg font-bold text-navy-ink hover:bg-tint"
            onClick={() => svgRef.current && zoomRef.current && select(svgRef.current).call(zoomRef.current.scaleBy, k as number)}>{label}</button>
        ))}
        <button type="button" className="h-8 rounded border border-line bg-white px-2 text-xs font-semibold text-navy-ink hover:bg-tint"
          onClick={() => svgRef.current && zoomRef.current && select(svgRef.current).call(zoomRef.current.transform, home())}>Reset view</button>
      </div>
    </div>
  );
}
