import type { ValidationResponse } from "../api/types";
import { Alert, Badge, Notice, Spinner } from "./ui";

interface ValidationViewProps {
  validation: ValidationResponse | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
}

const SEVERITY_LABEL: Record<"E" | "W", string> = { E: "Error", W: "Warning" };

export function ValidationView({ validation, loading, error, onSelect }: ValidationViewProps) {
  return (
    <section aria-label="Validation findings" className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold text-slate-900">Validation</h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading && validation === null ? <Spinner label="Validating…" /> : null}
      {validation !== null ? (
        <>
          <p className="text-sm text-slate-700">
            Errors: {validation.error_count} · Warnings: {validation.warning_count}
          </p>
          {validation.findings.length === 0 ? (
            <Notice>No findings. The repository is valid.</Notice>
          ) : (
            <ul className="flex flex-col gap-2">
              {validation.findings.map((finding, index) => (
                <li
                  key={`${finding.code}-${finding.doc_id ?? ""}-${index}`}
                  className="flex flex-col gap-1 rounded-md border border-slate-200 bg-white p-3 text-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={finding.severity === "E" ? "warn" : "neutral"}>{SEVERITY_LABEL[finding.severity]}</Badge>
                    <span className="font-mono text-xs">{finding.code}</span>
                    {finding.doc_id ? (
                      <button
                        type="button"
                        aria-label={`Open ${finding.doc_id}`}
                        onClick={() => onSelect(finding.doc_id as string)}
                        className="font-mono text-xs text-indigo-700 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
                      >
                        {finding.doc_id}
                      </button>
                    ) : finding.path ? (
                      // Repository paths are displayed as escaped text only: no link, no action.
                      <span className="break-all font-mono text-xs text-slate-700">{finding.path}</span>
                    ) : null}
                  </div>
                  <p className="text-slate-800">{finding.message}</p>
                  {finding.fix ? <p className="text-xs text-slate-600">Fix: {finding.fix}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </section>
  );
}
