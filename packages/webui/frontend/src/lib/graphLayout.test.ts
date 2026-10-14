import { describe, expect, it } from "vitest";
import { GRAPH_NODE_LIMIT, layoutGraph, prepareGraph } from "./graphLayout";
import type { GraphResponse } from "../api/types";

function bigGraph(count: number): GraphResponse {
  const nodes = Array.from({ length: count }, (_, i) => ({
    id: `RE-${String(i).padStart(6, "0")}`,
    title: `Node ${i}`,
    kind: i % 2 === 0 ? "requirement" : "goal",
  }));
  const edges = nodes.slice(1).map((node, i) => ({
    source: node.id,
    type: "refines",
    target: nodes[i]!.id,
  }));
  return { nodes, edges, truncated: false };
}

describe("prepareGraph", () => {
  it("draws at most 300 nodes, flags truncation, and keeps only edges between drawn nodes", () => {
    expect(GRAPH_NODE_LIMIT).toBe(300);
    const prepared = prepareGraph(bigGraph(305));

    expect(prepared.nodes).toHaveLength(300);
    expect(prepared.truncated).toBe(true);
    expect(prepared.nodeCount).toBe(305);
    const visible = new Set(prepared.nodes.map((n) => n.id));
    for (const edge of prepared.edges) {
      expect(visible.has(edge.source)).toBe(true);
      expect(visible.has(edge.target)).toBe(true);
    }
  });

  it("keeps the backend truncation flag even when nothing is cut client-side", () => {
    const prepared = prepareGraph({ ...bigGraph(3), truncated: true });

    expect(prepared.nodes).toHaveLength(3);
    expect(prepared.truncated).toBe(true);
  });

  it("reports no truncation for a small complete graph", () => {
    const prepared = prepareGraph(bigGraph(4));

    expect(prepared.truncated).toBe(false);
    expect(prepared.edges).toHaveLength(3);
  });
});

describe("layoutGraph", () => {
  it("places nodes in one column per kind so kinds never overlap", () => {
    const layout = layoutGraph(
      [
        { id: "A", title: "a", kind: "goal" },
        { id: "B", title: "b", kind: "requirement" },
        { id: "C", title: "c", kind: "requirement" },
      ],
      [{ source: "B", type: "refines", target: "A" }],
    );

    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    expect(byId.get("A")?.x).not.toBe(byId.get("B")?.x);
    expect(byId.get("B")?.x).toBe(byId.get("C")?.x);
    expect(byId.get("B")?.y).not.toBe(byId.get("C")?.y);
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.height).toBeGreaterThan(0);
    expect(layout.edges[0]).toMatchObject({ type: "refines" });
  });
});
