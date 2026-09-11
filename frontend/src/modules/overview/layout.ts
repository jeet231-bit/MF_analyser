import type { GraphEdge, GraphNode } from "@/api/model";

export const NODE_W = 172;
export const NODE_H = 44;
const COL_GAP = 72;
const ROW_GAP = 16;
const PAD = 16;

const ROLE_ORDER: Record<string, number> = {
  input: 0,
  reference: 1,
  transformation: 2,
  calculation: 3,
  output: 4,
  external: 5,
};

export interface LayoutNode extends GraphNode {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LayoutEdge extends GraphEdge {
  path: string;
  strokeWidth: number;
}

export interface FlowLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  width: number;
  height: number;
}

/** Left-to-right columns by topological depth; rows within a column ordered by role, then name. */
export function layoutByDepth(nodes: GraphNode[], edges: GraphEdge[]): FlowLayout {
  const columns = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const list = columns.get(n.depth) ?? [];
    list.push(n);
    columns.set(n.depth, list);
  }
  const depths = [...columns.keys()].sort((a, b) => a - b);
  const tallest = Math.max(0, ...[...columns.values()].map((c) => c.length));
  const height = PAD * 2 + Math.max(1, tallest) * NODE_H + Math.max(0, tallest - 1) * ROW_GAP;

  const placed = new Map<string, LayoutNode>();
  depths.forEach((depth, colIndex) => {
    const list = (columns.get(depth) ?? []).slice().sort((a, b) => {
      const ra = ROLE_ORDER[a.kind] ?? 9;
      const rb = ROLE_ORDER[b.kind] ?? 9;
      return ra - rb || a.label.localeCompare(b.label);
    });
    const colHeight = list.length * NODE_H + (list.length - 1) * ROW_GAP;
    const top = PAD + (height - PAD * 2 - colHeight) / 2;
    list.forEach((n, i) => {
      placed.set(n.id, {
        ...n,
        x: PAD + colIndex * (NODE_W + COL_GAP),
        y: top + i * (NODE_H + ROW_GAP),
        w: NODE_W,
        h: NODE_H,
      });
    });
  });

  const maxWeight = Math.max(1, ...edges.map((e) => e.weight));
  const laidEdges: LayoutEdge[] = [];
  for (const e of edges) {
    const s = placed.get(e.source);
    const t = placed.get(e.target);
    if (!s || !t) continue;
    const x1 = s.x + s.w;
    const y1 = s.y + s.h / 2;
    const x2 = t.x;
    const y2 = t.y + t.h / 2;
    const cx = (x1 + x2) / 2;
    laidEdges.push({
      ...e,
      path: `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`,
      strokeWidth: 1 + 2 * Math.log1p(e.weight) / Math.log1p(maxWeight),
    });
  }

  const width = PAD * 2 + depths.length * NODE_W + Math.max(0, depths.length - 1) * COL_GAP;
  return { nodes: [...placed.values()], edges: laidEdges, width, height };
}
