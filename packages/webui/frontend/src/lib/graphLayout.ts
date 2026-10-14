import type { GraphEdge, GraphNode, GraphResponse } from "../api/types";

/** The drawn graph never exceeds this many nodes (the UI shows a truncation notice). */
export const GRAPH_NODE_LIMIT = 300;

export interface PreparedGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  nodeCount: number;
}

/** Caps the drawn graph at `limit` nodes; edges are kept only when both endpoints are drawn. */
export function prepareGraph(graph: GraphResponse, limit: number = GRAPH_NODE_LIMIT): PreparedGraph {
  const nodes = graph.nodes.slice(0, limit);
  const visible = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target));
  return {
    nodes,
    edges,
    truncated: graph.truncated || graph.nodes.length > nodes.length,
    nodeCount: graph.nodes.length,
  };
}

const KIND_ORDER = ["goal", "requirement", "design", "verification", "information"];

export interface PositionedNode {
  id: string;
  title: string | null;
  kind: string;
  x: number;
  y: number;
}

export interface PositionedEdge {
  key: string;
  type: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface GraphLayout {
  width: number;
  height: number;
  nodes: PositionedNode[];
  edges: PositionedEdge[];
}

export const LAYOUT = {
  columnWidth: 240,
  rowHeight: 56,
  padding: 24,
  nodeWidth: 200,
  nodeHeight: 40,
} as const;

/**
 * Lays nodes out in one column per kind (goal, requirement, design, ...), in a stable order.
 * Columns keep the diagram readable without an external layout library.
 */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): GraphLayout {
  const kinds = [...new Set(nodes.map((node) => node.kind))].sort(compareKinds);
  const columnOf = new Map(kinds.map((kind, index) => [kind, index]));
  const rowCounter = new Map<string, number>();
  const positioned = new Map<string, PositionedNode>();

  const sorted = [...nodes].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const node of sorted) {
    const column = columnOf.get(node.kind) ?? 0;
    const row = rowCounter.get(node.kind) ?? 0;
    rowCounter.set(node.kind, row + 1);
    positioned.set(node.id, {
      id: node.id,
      title: node.title,
      kind: node.kind,
      x: LAYOUT.padding + column * LAYOUT.columnWidth,
      y: LAYOUT.padding + row * LAYOUT.rowHeight,
    });
  }

  const centre = (node: PositionedNode) => ({
    x: node.x + LAYOUT.nodeWidth / 2,
    y: node.y + LAYOUT.nodeHeight / 2,
  });
  const positionedEdges: PositionedEdge[] = [];
  edges.forEach((edge, index) => {
    const from = positioned.get(edge.source);
    const to = positioned.get(edge.target);
    if (!from || !to) {
      return;
    }
    const a = centre(from);
    const b = centre(to);
    positionedEdges.push({
      key: `${index}:${edge.source}:${edge.type}:${edge.target}`,
      type: edge.type,
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
    });
  });

  const columns = Math.max(kinds.length, 1);
  const tallest = Math.max(0, ...[...rowCounter.values()]);
  return {
    width: LAYOUT.padding * 2 + columns * LAYOUT.columnWidth,
    height: LAYOUT.padding * 2 + Math.max(tallest, 1) * LAYOUT.rowHeight,
    nodes: [...positioned.values()],
    edges: positionedEdges,
  };
}

function compareKinds(a: string, b: string): number {
  const ia = KIND_ORDER.indexOf(a);
  const ib = KIND_ORDER.indexOf(b);
  const ra = ia === -1 ? KIND_ORDER.length : ia;
  const rb = ib === -1 ? KIND_ORDER.length : ib;
  if (ra !== rb) {
    return ra - rb;
  }
  return a < b ? -1 : a > b ? 1 : 0;
}
