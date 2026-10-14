import { useCallback, useRef, useState } from "react";
import type { Api } from "./api/client";
import type { DocumentFilters, SessionInfo } from "./api/types";
import { CreateDocumentDialog } from "./components/CreateDocumentDialog";
import { DocumentDetail } from "./components/DocumentDetail";
import { DocumentList } from "./components/DocumentList";
import { GraphView } from "./components/GraphView";
import { StatusCards } from "./components/StatusCards";
import { ValidationView } from "./components/ValidationView";
import { Alert, Badge, Spinner } from "./components/ui";
import { useLoader } from "./lib/useLoader";

type Tab = "documents" | "graph" | "validation";

const TABS: { id: Tab; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "graph", label: "Graph" },
  { id: "validation", label: "Validation" },
];

const NO_FILTERS: DocumentFilters = { type: "", q: "", status: "" };

interface AppProps {
  session: SessionInfo;
  api: Api;
}

/**
 * Single-page shell. Every mutation bumps `refreshToken`, which refetches the views it can affect.
 * Only the currently selected document is ever rendered or mutated; late responses for other
 * documents are ignored by the loader and by the detail guard below.
 */
export function App({ session, api }: AppProps) {
  const [tab, setTab] = useState<Tab>("documents");
  const [filters, setFilters] = useState<DocumentFilters>(NO_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [creating, setCreating] = useState(false);
  // Bumped when an unsaved draft is discarded, so the editor remounts empty.
  const [editorEpoch, setEditorEpoch] = useState(0);
  const dirtyRef = useRef(false);

  const list = useLoader(() => api.listDocuments(filters), [api, filters, refreshToken]);
  const allDocuments = useLoader(() => api.listDocuments(), [api, refreshToken]);
  const status = useLoader(() => api.getStatus(), [api, refreshToken]);
  const validation = useLoader(() => api.getValidation(), [api, refreshToken]);
  const graph = useLoader(tab === "graph" ? () => api.getGraph() : null, [api, refreshToken, tab]);
  const detail = useLoader(
    selectedId === null ? null : () => api.getDocument(selectedId),
    [api, selectedId, refreshToken],
  );

  const onChanged = useCallback(() => setRefreshToken((value) => value + 1), []);
  const onDirtyChange = useCallback((dirty: boolean) => {
    dirtyRef.current = dirty;
  }, []);

  /** Returns false when the user keeps an unsaved draft instead of abandoning it. */
  function confirmLeave(): boolean {
    if (!dirtyRef.current) {
      return true;
    }
    if (window.confirm("Discard unsaved changes to this document?")) {
      dirtyRef.current = false;
      return true;
    }
    return false;
  }

  /** New document uses the same unsaved-draft guard as any other navigation. */
  function openCreate() {
    if (dirtyRef.current) {
      if (!confirmLeave()) {
        return;
      }
      setEditorEpoch((value) => value + 1);
    }
    setCreating(true);
  }

  function selectDocument(id: string) {
    if (id !== selectedId && !confirmLeave()) {
      return;
    }
    setSelectedId(id);
    setTab("documents");
  }

  function navigate(next: Tab) {
    if (next === tab) {
      return;
    }
    if (tab === "documents" && !confirmLeave()) {
      return;
    }
    setTab(next);
  }

  // Guard: only show a document whose response belongs to the current selection.
  const current = detail.data !== null && detail.data.id === selectedId ? detail.data : null;

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      {/* While the create dialog is open the page behind it is inert (modal, not just visually covered). */}
      <div inert={creating ? true : undefined}>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div>
              <h1 className="text-lg font-bold tracking-tight">GREGraph</h1>
              <p className="text-xs text-slate-600">
                Local workspace: <span className="font-mono">{session.repository.name}</span>
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {session.repository.degraded || !session.repository.git ? <Badge tone="warn">No Git</Badge> : null}
              <nav aria-label="Primary" className="flex gap-1 rounded-lg bg-slate-100 p-1">
                {TABS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={tab === item.id ? "page" : undefined}
                    onClick={() => navigate(item.id)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 ${
                      tab === item.id ? "bg-white text-indigo-800 shadow-sm" : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </div>
          </div>
        </header>

        <main className="mx-auto flex max-w-7xl flex-col gap-6 p-4">
          {tab === "documents" ? (
            <>
              <StatusCards
                status={status.data}
                loading={status.loading}
                error={status.error}
                onSelect={selectDocument}
              />
              <div className="grid gap-6 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
                <DocumentList
                  items={list.data?.items ?? null}
                  notices={list.data?.notices ?? []}
                  loading={list.loading}
                  error={list.error}
                  filters={filters}
                  types={session.types}
                  selectedId={selectedId}
                  onFiltersChange={setFilters}
                  onSelect={selectDocument}
                  onCreate={openCreate}
                />
                <div className="min-w-0">
                  {selectedId === null ? (
                    <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">
                      Select a document to see its body, tags, and links.
                    </p>
                  ) : current !== null ? (
                    <DocumentDetail
                      key={`${editorEpoch}:${current.id}`}
                      doc={current}
                      api={api}
                      linkTypes={session.link_types}
                      documents={allDocuments.data?.items ?? []}
                      onSelect={selectDocument}
                      onChanged={onChanged}
                      onDirtyChange={onDirtyChange}
                    />
                  ) : detail.error !== null ? (
                    <Alert>{detail.error}</Alert>
                  ) : (
                    <Spinner label="Loading document…" />
                  )}
                </div>
              </div>
            </>
          ) : null}

          {tab === "graph" ? (
            <GraphView graph={graph.data} loading={graph.loading} error={graph.error} onSelect={selectDocument} />
          ) : null}

          {tab === "validation" ? (
            <ValidationView
              validation={validation.data}
              loading={validation.loading}
              error={validation.error}
              onSelect={selectDocument}
            />
          ) : null}
        </main>
      </div>

      {creating ? (
        <CreateDocumentDialog
          types={session.types}
          api={api}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            dirtyRef.current = false;
            setSelectedId(id);
            setTab("documents");
            onChanged();
          }}
        />
      ) : null}
    </div>
  );
}
