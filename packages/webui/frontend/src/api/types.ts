// Mirrors the fixed backend contract for the local web UI (GET /api/... and mutations).
// Keep in sync with packages/webui/src/gregraph/webui/ when the backend changes.

/** Core severity: `E` = error, `W` = warning (spec 14). The backend sends no other value. */
export type Severity = "E" | "W";

export interface Finding {
  code: string;
  severity: Severity;
  message: string;
  /** Set when the subject is a document; null otherwise. */
  doc_id?: string | null;
  /** Set when the subject is a repository path; null otherwise. Shown as escaped text only. */
  path?: string | null;
  fix?: string | null;
}

export interface SessionInfo {
  repository: { name: string; git: boolean; degraded: boolean };
  types: { name: string; kind: string }[];
  link_types: string[];
  version: string;
  csrf_token: string;
}

export interface DocumentSummary {
  id: string;
  type: string;
  kind: string;
  status: string;
  version: number;
  title: string | null;
  tags: string[];
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  notices: string[];
}

export interface OutboundLink {
  type: string;
  target: string;
  outdated: boolean;
}

export interface InboundLink {
  type: string;
  source: string;
  outdated: boolean;
}

export interface DocumentDetail extends DocumentSummary {
  body_text: string;
  body_hash: string;
  outbound: OutboundLink[];
  inbound: InboundLink[];
  notices: string[];
}

export interface StatusResponse {
  counts: Record<string, number>;
  degraded: boolean;
  pending: string[];
  outdated: string[];
  stale: string[];
  findings: Finding[];
  [key: string]: unknown;
}

export interface ValidationResponse {
  findings: Finding[];
  error_count: number;
  warning_count: number;
}

export interface GraphNode {
  id: string;
  title: string | null;
  kind: string;
}

export interface GraphEdge {
  source: string;
  type: string;
  target: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}

export interface DocumentFilters {
  type?: string;
  q?: string;
  status?: string;
}

export interface CreateDocumentInput {
  type: string;
  title: string;
  tags: string[];
}

export interface CreateDocumentResponse {
  id: string;
  notices: string[];
  findings: Finding[];
}

export interface SaveBodyResponse {
  id: string;
  body_hash: string;
  title: string | null;
  changed: boolean;
  findings: Finding[];
}

export interface UpdateTagsResponse {
  id: string;
  tags: string[];
  notices: string[];
}

export interface LinkInput {
  source: string;
  type: string;
  target: string;
}

export interface CreateLinkResponse {
  created: boolean;
  notices: string[];
}

export interface RemoveLinkResponse {
  removed: boolean;
  notices: string[];
}
