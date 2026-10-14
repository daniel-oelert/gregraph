import type {
  DocumentDetail,
  DocumentSummary,
  GraphResponse,
  SessionInfo,
  StatusResponse,
  ValidationResponse,
} from "../api/types";
import type { Api } from "../api/client";
import { vi, type Mock } from "vitest";

export const session: SessionInfo = {
  repository: { name: "demo-repo", git: true, degraded: false },
  types: [
    { name: "feature", kind: "requirement" },
    { name: "goal", kind: "goal" },
    { name: "test-case", kind: "verification" },
  ],
  link_types: ["refines", "depends-on", "verifies"],
  version: "0.1.0",
  csrf_token: "tok-session",
};

export const docA: DocumentDetail = {
  id: "RE-AAAAAA",
  type: "feature",
  kind: "requirement",
  status: "active",
  version: 2,
  title: "Upload documents",
  tags: ["core"],
  body_text: "# Upload documents\n\nOriginal body A",
  body_hash: "sha256:aaa",
  outbound: [{ type: "refines", target: "RE-BBBBBB", outdated: false }],
  inbound: [{ type: "verifies", source: "RE-CCCCCC", outdated: true }],
  notices: [],
};

export const docB: DocumentDetail = {
  id: "RE-BBBBBB",
  type: "goal",
  kind: "goal",
  status: "draft",
  version: 1,
  title: "Self-service",
  tags: [],
  body_text: "# Self-service\n\nBody B",
  body_hash: "sha256:bbb",
  outbound: [],
  inbound: [{ type: "refines", source: "RE-AAAAAA", outdated: false }],
  notices: [],
};

export const summaries: DocumentSummary[] = [
  { id: "RE-AAAAAA", type: "feature", kind: "requirement", status: "active", version: 2, title: "Upload documents", tags: ["core"] },
  { id: "RE-BBBBBB", type: "goal", kind: "goal", status: "draft", version: 1, title: "Self-service", tags: [] },
  { id: "RE-CCCCCC", type: "test-case", kind: "verification", status: "active", version: 1, title: "Upload test", tags: [] },
];

export const status: StatusResponse = {
  counts: { draft: 1, active: 2, superseded: 0, deprecated: 0 },
  degraded: false,
  pending: ["RE-BBBBBB refines RE-AAAAAA"],
  outdated: [],
  stale: [],
  findings: [],
};

export const validation: ValidationResponse = {
  findings: [
    { code: "W-ORPHAN", severity: "W", message: "Document has no edges.", doc_id: "RE-BBBBBB", path: null, fix: null },
  ],
  error_count: 0,
  warning_count: 1,
};

export const graph: GraphResponse = {
  nodes: [
    { id: "RE-AAAAAA", title: "Upload documents", kind: "requirement" },
    { id: "RE-BBBBBB", title: "Self-service", kind: "goal" },
  ],
  edges: [{ source: "RE-AAAAAA", type: "refines", target: "RE-BBBBBB" }],
  truncated: false,
};

export type Spies = { [K in keyof Api]: Mock<Api[K]> };

const defaults: Api = {
  listDocuments: async () => ({ items: summaries, notices: [] }),
  getDocument: async (id: string) => (id === docB.id ? docB : docA),
  createDocument: async () => ({ id: "RE-NEW001", notices: [], findings: [] }),
  saveBody: async (id: string) => ({ id, body_hash: "sha256:new", title: "Upload documents", changed: true, findings: [] }),
  updateTags: async (id: string, tags: string[]) => ({ id, tags, notices: [] }),
  createLink: async () => ({ created: true, notices: [] }),
  removeLink: async () => ({ removed: true, notices: [] }),
  getStatus: async () => status,
  getValidation: async () => validation,
  getGraph: async () => graph,
};

/** Builds a fake Api whose every method is a vitest spy with sensible defaults. */
export function makeApi(overrides: Partial<Api> = {}): Spies {
  const spies = {} as Record<keyof Api, unknown>;
  for (const key of Object.keys(defaults) as (keyof Api)[]) {
    spies[key] = vi.fn(overrides[key] ?? defaults[key]);
  }
  return spies as Spies;
}
