import type { FormEvent } from "react";
import type { DocumentFilters, DocumentSummary, SessionInfo } from "../api/types";
import { Alert, Badge, Button, Notice, Spinner } from "./ui";

/** Core states (spec 8) plus `unknown`, which the backend reports when Git status is unavailable. */
export const STATUS_CHOICES = ["draft", "active", "superseded", "deprecated", "unknown"];

interface DocumentListProps {
  items: DocumentSummary[] | null;
  notices: string[];
  loading: boolean;
  error: string | null;
  filters: DocumentFilters;
  types: SessionInfo["types"];
  selectedId: string | null;
  onFiltersChange: (filters: DocumentFilters) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
}

export function DocumentList({
  items,
  notices,
  loading,
  error,
  filters,
  types,
  selectedId,
  onFiltersChange,
  onSelect,
  onCreate,
}: DocumentListProps) {
  function update(patch: Partial<DocumentFilters>) {
    onFiltersChange({ ...filters, ...patch });
  }

  function preventSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }

  return (
    <section aria-label="Document list" className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">Documents</h2>
        <Button variant="primary" onClick={onCreate}>
          New document
        </Button>
      </div>
      <form role="search" onSubmit={preventSubmit} className="grid gap-2 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
        <label className="flex flex-col text-xs font-medium text-slate-600 sm:col-span-3 lg:col-span-1 xl:col-span-3">
          <span className="mb-1">Search documents</span>
          <input
            type="search"
            aria-label="Search documents"
            value={filters.q ?? ""}
            onChange={(event) => update({ q: event.target.value })}
            placeholder="Title or ID"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm font-normal text-slate-900"
          />
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-600">
          <span className="mb-1">Type</span>
          <select
            aria-label="Type"
            value={filters.type ?? ""}
            onChange={(event) => update({ type: event.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm font-normal text-slate-900"
          >
            <option value="">All types</option>
            {types.map((type) => (
              <option key={type.name} value={type.name}>
                {type.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-600">
          <span className="mb-1">Status</span>
          <select
            aria-label="Status"
            value={filters.status ?? ""}
            onChange={(event) => update({ status: event.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm font-normal text-slate-900"
          >
            <option value="">All statuses</option>
            {STATUS_CHOICES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
      </form>

      {notices.map((notice) => (
        <Notice key={notice} tone="warn">
          {notice}
        </Notice>
      ))}
      {error ? <Alert>{error}</Alert> : null}
      {loading && items === null ? <Spinner label="Loading documents…" /> : null}

      {items !== null && items.length === 0 && !loading && error === null ? (
        <p className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
          No documents match these filters.
        </p>
      ) : null}

      {items !== null && items.length > 0 ? (
        <ul aria-label="Documents" className="flex max-h-[70vh] flex-col gap-2 overflow-auto pr-1">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                aria-current={item.id === selectedId ? "true" : undefined}
                onClick={() => onSelect(item.id)}
                className={`flex w-full flex-col gap-1 rounded-md border p-3 text-left text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 ${
                  item.id === selectedId
                    ? "border-indigo-400 bg-indigo-50"
                    : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                }`}
              >
                <span className="font-medium text-slate-900 break-words">{item.title ?? item.id}</span>
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
                  <span className="font-mono">{item.id}</span>
                  <Badge>{item.type}</Badge>
                  <Badge tone={item.status === "draft" ? "warn" : "neutral"}>{item.status}</Badge>
                  <span>v{item.version}</span>
                  {item.tags.map((tag) => (
                    <span key={tag} className="rounded bg-slate-100 px-1 text-slate-700">
                      #{tag}
                    </span>
                  ))}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
