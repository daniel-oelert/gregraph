import { useMemo } from "react";
import type { GraphResponse } from "../api/types";
import { layoutGraph, LAYOUT, prepareGraph } from "../lib/graphLayout";
import { Alert, Notice, Spinner } from "./ui";

interface GraphViewProps {
  graph: GraphResponse | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
}

export function GraphView({ graph, loading, error, onSelect }: GraphViewProps) {
  const prepared = useMemo(() => (graph ? prepareGraph(graph) : null), [graph]);
  const layout = useMemo(
    () => (prepared ? layoutGraph(prepared.nodes, prepared.edges) : null),
    [prepared],
  );

  return (
    <section aria-label="Graph" className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold text-slate-900">Graph</h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading && graph === null ? <Spinner label="Loading graph…" /> : null}
      {prepared !== null && prepared.truncated ? (
        <Notice tone="warn">
          Graph truncated: showing {prepared.nodes.length} of {prepared.nodeCount} nodes (limit 300).
        </Notice>
      ) : null}
      {prepared !== null && prepared.nodes.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
          No documents yet. Create one to start the graph.
        </p>
      ) : null}
      {layout !== null && layout.nodes.length > 0 ? (
        <div className="max-h-[70vh] overflow-auto rounded-lg bg-white p-2 ring-1 ring-slate-200">
          <svg
            role="group"
            aria-label="Document graph"
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            className="min-w-full"
          >
            {layout.edges.map((edge) => (
              <line
                key={edge.key}
                x1={edge.x1}
                y1={edge.y1}
                x2={edge.x2}
                y2={edge.y2}
                strokeWidth={1.5}
                strokeDasharray={edge.type === "refines" ? undefined : "4 3"}
                className="stroke-slate-400"
              >
                <title>{edge.type}</title>
              </line>
            ))}
            {layout.nodes.map((node) => (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`${node.id} ${node.title ?? ""}`.trim()}
                onClick={() => onSelect(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(node.id);
                  }
                }}
                className="cursor-pointer outline-none focus-visible:[&>rect]:stroke-indigo-600 focus-visible:[&>rect]:stroke-2"
              >
                <rect
                  x={node.x}
                  y={node.y}
                  width={LAYOUT.nodeWidth}
                  height={LAYOUT.nodeHeight}
                  rx={6}
                  className="fill-white stroke-slate-400 hover:fill-indigo-50"
                />
                <text x={node.x + 8} y={node.y + 16} className="fill-slate-500 text-[10px]">
                  {node.id} · {node.kind}
                </text>
                <text x={node.x + 8} y={node.y + 31} className="fill-slate-900 text-[12px]">
                  {truncateLabel(node.title ?? node.id)}
                </text>
              </g>
            ))}
          </svg>
        </div>
      ) : null}
    </section>
  );
}

function truncateLabel(text: string): string {
  return text.length > 26 ? `${text.slice(0, 25)}…` : text;
}
