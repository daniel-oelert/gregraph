import type { Api } from "../api/client";
import type { DocumentDetail as DocumentData, DocumentSummary } from "../api/types";
import { BodyEditor } from "./BodyEditor";
import { LinksPanel } from "./LinksPanel";
import { TagsEditor } from "./TagsEditor";
import { Badge, Notice } from "./ui";

export interface DocumentDetailProps {
  doc: DocumentData;
  api: Api;
  linkTypes: string[];
  documents: DocumentSummary[];
  onSelect: (id: string) => void;
  onChanged: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

export function DocumentDetail({
  doc,
  api,
  linkTypes,
  documents,
  onSelect,
  onChanged,
  onDirtyChange,
}: DocumentDetailProps) {
  const noop = () => undefined;
  return (
    <article className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h2 className="text-xl font-semibold text-slate-900 break-words">{doc.title ?? doc.id}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <span className="font-mono">{doc.id}</span>
          <Badge>{doc.type}</Badge>
          <Badge>{doc.kind}</Badge>
          <Badge tone={doc.status === "draft" ? "warn" : "good"}>{doc.status}</Badge>
          <Badge>v{doc.version}</Badge>
        </div>
        {doc.notices.map((notice) => (
          <Notice key={notice} tone="warn">
            {notice}
          </Notice>
        ))}
      </header>
      <LinksPanel
        key={`links-${doc.id}`}
        doc={doc}
        api={api}
        linkTypes={linkTypes}
        documents={documents}
        onSelect={onSelect}
        onChanged={onChanged}
      />
      <TagsEditor key={`tags-${doc.id}`} doc={doc} api={api} onChanged={onChanged} />
      <BodyEditor
        key={`body-${doc.id}`}
        doc={doc}
        api={api}
        onChanged={onChanged}
        onDirtyChange={onDirtyChange ?? noop}
      />
    </article>
  );
}
