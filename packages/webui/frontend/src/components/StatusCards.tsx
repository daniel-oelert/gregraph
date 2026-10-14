import type { StatusResponse } from "../api/types";
import { parseStatusLabel } from "../lib/statusLabels";
import { Alert, Badge, Spinner } from "./ui";

interface StatusCardsProps {
  status: StatusResponse | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
}

export function StatusCards({ status, loading, error, onSelect }: StatusCardsProps) {
  return (
    <section aria-label="Status summary" className="flex flex-col gap-3">
      {error ? <Alert>{error}</Alert> : null}
      {loading && status === null ? <Spinner label="Loading status…" /> : null}
      {status !== null ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
            {status.degraded ? <Badge tone="warn">Degraded: Git unavailable</Badge> : <Badge tone="good">Git-aware</Badge>}
            <span>{status.findings.length} findings</span>
          </div>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.entries(status.counts).map(([name, count]) => (
              <div key={name} className="rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200">
                <dt className="text-xs uppercase tracking-wide text-slate-500">{name}</dt>
                <dd className="text-2xl font-semibold text-slate-900">{count}</dd>
              </div>
            ))}
          </dl>
          <LabelList label="Pending (unbumped changes)" labels={status.pending} onSelect={onSelect} />
          <LabelList label="Outdated links" labels={status.outdated} onSelect={onSelect} />
          <LabelList label="Stale links" labels={status.stale} onSelect={onSelect} />
        </>
      ) : null}
    </section>
  );
}

const LABEL_CLASS = "rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs";

/**
 * Renders backend labels. The full label stays visible; a click opens only the SOURCE document.
 * Malformed entries are plain text: they never become an ID passed to the API.
 */
function LabelList({
  label,
  labels,
  onSelect,
}: {
  label: string;
  labels: string[];
  onSelect: (id: string) => void;
}) {
  if (labels.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-600">{label}:</span>
      {labels.map((text) => {
        const parsed = parseStatusLabel(text);
        if (parsed === null) {
          return (
            <span key={text} className={`${LABEL_CLASS} text-slate-600`}>
              {text}
            </span>
          );
        }
        const target = parsed.kind === "document" ? parsed.id : parsed.source;
        return (
          <button
            key={text}
            type="button"
            onClick={() => onSelect(target)}
            className={`${LABEL_CLASS} text-indigo-800 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600`}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}
