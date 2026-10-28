// Minimal typings for the subset of d3-sankey used by the intake-triage chart (no @types package needed).
declare module "d3-sankey" {
  export interface SankeyNodeMinimal {
    x0?: number;
    x1?: number;
    y0?: number;
    y1?: number;
    value?: number;
    index?: number;
    depth?: number;
  }
  export interface SankeyLinkMinimal<N> {
    source: number | string | N;
    target: number | string | N;
    value: number;
    width?: number;
    y0?: number;
    y1?: number;
  }
  export interface SankeyGraph<N, L> {
    nodes: N[];
    links: L[];
  }
  export interface SankeyLayout<N, L> {
    (graph: SankeyGraph<N, L>): SankeyGraph<N & SankeyNodeMinimal, L & SankeyLinkMinimal<N & SankeyNodeMinimal>>;
    nodeId(fn: (node: N) => string | number): this;
    nodeWidth(width: number): this;
    nodePadding(padding: number): this;
    nodeSort(sort: ((a: N, b: N) => number) | null): this;
    linkSort(sort: ((a: L, b: L) => number) | null): this;
    nodeAlign(fn: (node: N, n: number) => number): this;
    extent(extent: [[number, number], [number, number]]): this;
    iterations(n: number): this;
  }
  export function sankey<N, L>(): SankeyLayout<N, L>;
  export function sankeyLinkHorizontal(): (link: any) => string | null;
  export function sankeyLeft(node: any, n: number): number;
  export function sankeyRight(node: any, n: number): number;
  export function sankeyJustify(node: any, n: number): number;
}
