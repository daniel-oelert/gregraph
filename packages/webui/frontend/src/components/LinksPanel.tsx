import { useState, type FormEvent } from "react";
import type { Api } from "../api/client";
import type { DocumentDetail as DocumentData, DocumentSummary } from "../api/types";
import { errorMessage } from "../lib/errors";
import { Alert, Badge, Button, Notice, Panel } from "./ui";

interface LinksPanelProps {
  doc: DocumentData;
  api: Api;
  linkTypes: string[];
  documents: DocumentSummary[];
  onSelect: (id: string) => void;
  onChanged: () => void;
}

export function LinksPanel({ doc, api, linkTypes, documents, onSelect, onChanged }: LinksPanelProps) {
  const [linkType, setLinkType] = useState(linkTypes[0] ?? "");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const targets = documents.filter((candidate) => candidate.id !== doc.id);

  async function remove(type: string, other: string) {
    setBusy(true);
    setError(null);
    try {
      await api.removeLink({ source: doc.id, type, target: other });
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (target === "" || linkType === "") {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.createLink({ source: doc.id, type: linkType, target });
      setNotices(result.notices);
      setTarget("");
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Links">
      {error ? <div className="mb-3"><Alert>{error}</Alert></div> : null}
      {notices.length > 0 ? (
        <div className="mb-3 flex flex-col gap-2">
          {notices.map((notice) => (
            <Notice key={notice}>{notice}</Notice>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-700">Outbound</h4>
          {doc.outbound.length === 0 ? (
            <p className="text-sm text-slate-500">No outbound links.</p>
          ) : (
            <ul aria-label="Outbound links" className="flex flex-col gap-2">
              {doc.outbound.map((link) => (
                <li key={`${link.type}:${link.target}`} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">{link.type}</span>
                  <button
                    type="button"
                    className="font-medium text-indigo-700 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
                    onClick={() => onSelect(link.target)}
                  >
                    {link.target}
                  </button>
                  {link.outdated ? <Badge tone="warn">outdated</Badge> : null}
                  <Button
                    variant="danger"
                    className="px-2 py-0.5 text-xs"
                    disabled={busy}
                    aria-label={`Remove ${link.type} link to ${link.target}`}
                    onClick={() => void remove(link.type, link.target)}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-700">Inbound</h4>
          {doc.inbound.length === 0 ? (
            <p className="text-sm text-slate-500">No inbound links.</p>
          ) : (
            <ul aria-label="Inbound links" className="flex flex-col gap-2">
              {doc.inbound.map((link) => (
                <li key={`${link.type}:${link.source}`} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">{link.type}</span>
                  <button
                    type="button"
                    className="font-medium text-indigo-700 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
                    onClick={() => onSelect(link.source)}
                  >
                    {link.source}
                  </button>
                  {link.outdated ? <Badge tone="warn">outdated</Badge> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <form onSubmit={(event) => void create(event)} className="mt-4 flex flex-wrap items-end gap-2 border-t border-slate-200 pt-4">
        <label className="flex flex-col text-sm text-slate-700">
          <span className="mb-1">Link type</span>
          <select
            aria-label="Link type"
            value={linkType}
            onChange={(event) => setLinkType(event.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {linkTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-1 flex-col text-sm text-slate-700">
          <span className="mb-1">Target</span>
          <select
            aria-label="Target document"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            className="min-w-0 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Choose a document…</option>
            {targets.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.id} {candidate.title ?? ""}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="primary" disabled={busy || target === "" || linkType === ""}>
          Add link
        </Button>
      </form>
    </Panel>
  );
}
