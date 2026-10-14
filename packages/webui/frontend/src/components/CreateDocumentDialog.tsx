import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Api } from "../api/client";
import type { SessionInfo } from "../api/types";
import { errorMessage } from "../lib/errors";
import { Alert, Button } from "./ui";

interface CreateDocumentDialogProps {
  types: SessionInfo["types"];
  api: Api;
  onClose: () => void;
  onCreated: (id: string) => void;
}

/** The system change-request type is never offered for document creation (spec 9). */
export function creatableTypes(types: SessionInfo["types"]): SessionInfo["types"] {
  return types.filter((type) => type.name !== "cr");
}

export function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => tag !== "");
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keeps Tab and Shift+Tab inside the dialog while it is open (aria-modal). */
function trapTab(event: KeyboardEvent, root: HTMLElement | null): void {
  if (root === null) {
    return;
  }
  const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
  const first = items[0];
  const last = items[items.length - 1];
  if (first === undefined || last === undefined) {
    return;
  }
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault();
    first.focus();
  }
}

export function CreateDocumentDialog({ types, api, onClose, onCreated }: CreateDocumentDialogProps) {
  const choices = creatableTypes(types);
  const [type, setType] = useState(choices[0]?.name ?? "");
  const [title, setTitle] = useState("");
  const [tagText, setTagText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Mirrors `busy` for the document-level key handler, which must read the current value.
  const busyRef = useRef(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // Latest callback without re-running the focus effect: a parent re-render must not move focus.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    titleRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        // While a create request is pending the dialog stays open: closing it would let the
        // background page be edited, and a late success would then discard that draft.
        if (!busyRef.current) {
          onCloseRef.current();
        }
        return;
      }
      if (event.key === "Tab") {
        trapTab(event, dialogRef.current);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current) {
      return;
    }
    const cleanTitle = title.trim();
    if (cleanTitle === "") {
      setError("Title is required.");
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api.createDocument({ type, title: cleanTitle, tags: parseTags(tagText) });
      onCreated(result.id);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Create document"
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
      >
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Create document</h2>
        <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
          {error ? <Alert>{error}</Alert> : null}
          <label className="flex flex-col gap-1 text-sm text-slate-700">
            <span>Document type</span>
            <select
              aria-label="Document type"
              value={type}
              onChange={(event) => setType(event.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5"
            >
              {choices.map((choice) => (
                <option key={choice.name} value={choice.name}>
                  {choice.name} ({choice.kind})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-700">
            <span>Title</span>
            <input
              ref={titleRef}
              aria-label="Title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-700">
            <span>Tags (comma separated, optional)</span>
            <input
              aria-label="Tags"
              value={tagText}
              onChange={(event) => setTagText(event.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              Create
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
