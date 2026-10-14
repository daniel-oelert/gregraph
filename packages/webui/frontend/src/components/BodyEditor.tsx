import { useEffect, useRef, useState } from "react";
import type { Api } from "../api/client";
import { isStaleError } from "../api/client";
import type { DocumentDetail as DocumentData, Finding } from "../api/types";
import { errorMessage } from "../lib/errors";
import { Alert, Button, Notice } from "./ui";

interface BodyEditorProps {
  doc: DocumentData;
  api: Api;
  onChanged: () => void;
  onDirtyChange: (dirty: boolean) => void;
}

/**
 * Raw Markdown body viewer/editor. Saves carry the hash the draft started from
 * (optimistic concurrency). A 409 keeps the draft and requires an explicit reload;
 * the editor never resubmits with an older hash on its own.
 */
/**
 * Mirrors core update_body (spec 21.5): the only text change on write is CRLF and CR to LF.
 * Trailing spaces, blank lines, empty text and a missing final newline are kept exactly as typed.
 */
export function normaliseWritten(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

export function BodyEditor({ doc, api, onChanged, onDirtyChange }: BodyEditorProps) {
  // The last body known to be on disk: the parent's props, or the text a successful save just wrote.
  // It can run ahead of a lagging parent refetch, so beginEdit and the read-only view use it, not props.
  const [snapshot, setSnapshot] = useState({ text: doc.body_text, hash: doc.body_hash });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [startText, setStartText] = useState("");
  const [baseHash, setBaseHash] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [latestText, setLatestText] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const dirty = editing && draft !== startText;

  // Background refetches update the snapshot only when the server content actually changed.
  // An active draft and its baseHash are never touched here (external changes still 409).
  useEffect(() => {
    setSnapshot((previous) =>
      previous.text === doc.body_text && previous.hash === doc.body_hash
        ? previous
        : { text: doc.body_text, hash: doc.body_hash },
    );
  }, [doc.body_text, doc.body_hash]);

  const dirtyRef = useRef(onDirtyChange);
  dirtyRef.current = onDirtyChange;
  useEffect(() => {
    dirtyRef.current(dirty);
  }, [dirty]);
  useEffect(() => () => dirtyRef.current(false), []);

  function beginEdit() {
    setDraft(snapshot.text);
    setStartText(snapshot.text);
    setBaseHash(snapshot.hash);
    setEditing(true);
    setStale(false);
    setLatestText(null);
    setError(null);
    setNotice(null);
  }

  function cancel() {
    setEditing(false);
    setDraft("");
    setStale(false);
    setLatestText(null);
    setError(null);
  }

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.saveBody(doc.id, { text: draft, base_hash: baseHash });
      // Acknowledge the write immediately: the snapshot becomes what was written, before any refetch.
      setSnapshot({ text: normaliseWritten(draft), hash: result.body_hash });
      setEditing(false);
      setStale(false);
      setLatestText(null);
      setFindings(result.findings);
      setNotice(
        "Saved to the working tree. The change is pending until gregraph sync or the pre-commit hook records the new version.",
      );
      onChanged();
    } catch (failure) {
      // Only E-BODY-STALE is a conflict. Any other refusal keeps the draft for a plain retry.
      if (isStaleError(failure)) {
        setStale(true);
        setError("This document changed since you started editing, so your draft was not saved.");
      } else {
        setStale(false);
        setError(errorMessage(failure));
      }
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    setError(null);
    try {
      const latest = await api.getDocument(doc.id);
      if (latest.id !== doc.id) {
        return;
      }
      setBaseHash(latest.body_hash);
      setLatestText(latest.body_text);
      setStale(false);
      setNotice("Latest version loaded. Compare it with your draft, then save again.");
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  return (
    <section aria-label="Body" className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Body (Markdown)</h3>
        {editing ? null : (
          <Button onClick={beginEdit} variant="primary">
            Edit body
          </Button>
        )}
      </div>

      {notice ? <div className="mb-3"><Notice>{notice}</Notice></div> : null}
      {findings.length > 0 ? (
        <ul className="mb-3 list-disc pl-5 text-sm text-amber-900">
          {findings.map((finding, index) => (
            <li key={`${finding.code}-${index}`}>
              {finding.code}: {finding.message}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <div className="mb-3 flex flex-col gap-2">
          <Alert>{error}</Alert>
          {stale ? (
            <div>
              <Button onClick={() => void reloadLatest()}>Reload latest version</Button>
              <span className="ml-2 text-xs text-slate-600">Your draft stays here until you save it again.</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {editing ? (
        <div className="flex flex-col gap-3">
          <label className="text-sm font-medium text-slate-700" htmlFor={`body-${doc.id}`}>
            Markdown body
          </label>
          <textarea
            id={`body-${doc.id}`}
            aria-label="Markdown body"
            className="min-h-64 w-full rounded-md border border-slate-300 p-3 font-mono text-sm leading-6 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:bg-slate-50 disabled:text-slate-500"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={false}
            // Locked while a save is in flight: the saved text is the draft at click time,
            // so keystrokes typed during the request cannot be discarded by the success path.
            disabled={saving}
          />
          <p className="text-xs text-slate-500">
            Saves are pending until the existing gregraph sync or pre-commit hook flow records the version bump and link
            checks.
          </p>
          {latestText !== null ? (
            <details open className="rounded-md border border-slate-200 bg-slate-50 p-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-700">Latest saved version (read-only)</summary>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-slate-800">
                {latestText}
              </pre>
            </details>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => void save()} disabled={saving}>
              Save body
            </Button>
            <Button onClick={cancel} disabled={saving}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <pre
          aria-label="Body text"
          className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-3 font-mono text-sm leading-6 text-slate-800"
        >
          {snapshot.text}
        </pre>
      )}
    </section>
  );
}
