import { useState, type FormEvent } from "react";
import type { Api } from "../api/client";
import type { DocumentDetail as DocumentData } from "../api/types";
import { errorMessage } from "../lib/errors";
import { Alert, Button, Panel } from "./ui";

interface TagsEditorProps {
  doc: DocumentData;
  api: Api;
  onChanged: () => void;
}

/** Tag chips with add/remove. Every change sends the whole list for the captured document id. */
export function TagsEditor({ doc, api, onChanged }: TagsEditorProps) {
  const [newTag, setNewTag] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function apply(tags: string[]) {
    setBusy(true);
    setError(null);
    try {
      await api.updateTags(doc.id, tags);
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const tag = newTag.trim();
    if (tag === "" || doc.tags.includes(tag)) {
      return;
    }
    setNewTag("");
    void apply([...doc.tags, tag]);
  }

  return (
    <Panel title="Tags">
      {error ? <div className="mb-3"><Alert>{error}</Alert></div> : null}
      {doc.tags.length === 0 ? (
        <p className="mb-3 text-sm text-slate-500">No tags.</p>
      ) : (
        <ul aria-label="Tags" className="mb-3 flex flex-wrap gap-2">
          {doc.tags.map((tag) => (
            <li key={tag} className="inline-flex items-center gap-1 rounded-full bg-indigo-50 py-0.5 pl-3 pr-1 text-sm text-indigo-900 ring-1 ring-inset ring-indigo-200">
              <span>{tag}</span>
              <button
                type="button"
                aria-label={`Remove tag ${tag}`}
                disabled={busy}
                onClick={() => void apply(doc.tags.filter((existing) => existing !== tag))}
                className="rounded-full px-1.5 text-indigo-700 hover:bg-indigo-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-sm text-slate-700">
          <span className="mb-1">New tag</span>
          <input
            aria-label="New tag"
            value={newTag}
            onChange={(event) => setNewTag(event.target.value)}
            className="w-44 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder="e.g. security"
          />
        </label>
        <Button type="submit" disabled={busy || newTag.trim() === ""}>
          Add tag
        </Button>
      </form>
    </Panel>
  );
}
