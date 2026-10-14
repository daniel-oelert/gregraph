import type {
  CreateDocumentInput,
  CreateDocumentResponse,
  CreateLinkResponse,
  DocumentDetail,
  DocumentFilters,
  DocumentListResponse,
  Finding,
  GraphResponse,
  LinkInput,
  RemoveLinkResponse,
  SaveBodyResponse,
  SessionInfo,
  StatusResponse,
  UpdateTagsResponse,
  ValidationResponse,
} from "./types";

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export const TOKEN_HEADER = "X-GREGraph-Token";

export class ApiError extends Error {
  readonly status: number;
  readonly finding: Finding | null;

  constructor(status: number, message: string, finding: Finding | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.finding = finding;
  }
}

/** True only when the backend refused a body save with E-BODY-STALE (spec 21.8). Other 409s are ordinary errors. */
export function isStaleError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.finding?.code === "E-BODY-STALE";
}

export interface ApiOptions {
  token: string;
  fetch?: FetchLike;
}

export interface Api {
  listDocuments(filters?: DocumentFilters): Promise<DocumentListResponse>;
  getDocument(id: string): Promise<DocumentDetail>;
  createDocument(input: CreateDocumentInput): Promise<CreateDocumentResponse>;
  saveBody(id: string, input: { text: string; base_hash: string }): Promise<SaveBodyResponse>;
  updateTags(id: string, tags: string[]): Promise<UpdateTagsResponse>;
  createLink(input: LinkInput): Promise<CreateLinkResponse>;
  removeLink(input: LinkInput): Promise<RemoveLinkResponse>;
  getStatus(): Promise<StatusResponse>;
  getValidation(): Promise<ValidationResponse>;
  getGraph(): Promise<GraphResponse>;
}

const defaultFetch: FetchLike = (input, init) => fetch(input, init);

/** Reads the session, including the csrf_token that mutations must echo in X-GREGraph-Token. */
export async function fetchSession(fetchImpl: FetchLike = defaultFetch): Promise<SessionInfo> {
  return request<SessionInfo>(fetchImpl, "GET", "/api/session", undefined, undefined);
}

export function createApi(options: ApiOptions): Api {
  const fetchImpl = options.fetch ?? defaultFetch;
  const token = options.token;
  const call = <T>(method: string, path: string, body?: unknown): Promise<T> =>
    request<T>(fetchImpl, method, path, body, method === "GET" ? undefined : token);

  return {
    listDocuments(filters = {}) {
      return call<DocumentListResponse>("GET", `/api/documents${queryString(filters)}`);
    },
    getDocument(id) {
      return call<DocumentDetail>("GET", `/api/documents/${seg(id)}`);
    },
    createDocument(input) {
      return call<CreateDocumentResponse>("POST", "/api/documents", input);
    },
    saveBody(id, input) {
      return call<SaveBodyResponse>("PUT", `/api/documents/${seg(id)}/body`, input);
    },
    updateTags(id, tags) {
      return call<UpdateTagsResponse>("PATCH", `/api/documents/${seg(id)}/meta`, { tags });
    },
    createLink(input) {
      return call<CreateLinkResponse>("POST", "/api/links", input);
    },
    removeLink(input) {
      const path = `/api/links/${seg(input.source)}/${seg(input.type)}/${seg(input.target)}`;
      return call<RemoveLinkResponse>("DELETE", path, {});
    },
    getStatus() {
      return call<StatusResponse>("GET", "/api/status");
    },
    getValidation() {
      return call<ValidationResponse>("GET", "/api/validate");
    },
    getGraph() {
      return call<GraphResponse>("GET", "/api/graph");
    },
  };
}

function seg(value: string): string {
  return encodeURIComponent(value);
}

function queryString(filters: DocumentFilters): string {
  const params = new URLSearchParams();
  for (const key of ["type", "q", "status"] as const) {
    const raw = filters[key];
    const value = raw?.trim() ?? "";
    if (value !== "") {
      params.set(key, value);
    }
  }
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

async function request<T>(
  fetchImpl: FetchLike,
  method: string,
  path: string,
  body: unknown,
  token: string | undefined,
): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "application/json" });
  if (token !== undefined) {
    headers.set(TOKEN_HEADER, token);
  }
  const init: RequestInit = { method, headers };
  if (method !== "GET") {
    init.body = JSON.stringify(body ?? {});
  }

  let response: Response;
  try {
    response = await fetchImpl(path, init);
  } catch {
    throw new ApiError(0, "Network error: the local GREGraph server is not reachable.");
  }

  const payload = await readJson(response);
  if (!response.ok) {
    throw errorFrom(response.status, payload);
  }
  return payload as T;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === "") {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function errorFrom(status: number, payload: unknown): ApiError {
  if (isRecord(payload) && isFinding(payload["error"])) {
    const finding = payload["error"];
    return new ApiError(status, finding.message, finding);
  }
  if (isRecord(payload) && "detail" in payload) {
    const detail = describeDetail(payload["detail"]);
    if (detail !== "") {
      return new ApiError(status, detail);
    }
  }
  return new ApiError(status, `Request failed with status ${status}.`);
}

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (isRecord(item) && typeof item["msg"] === "string" ? item["msg"] : ""))
      .filter((msg) => msg !== "")
      .join("; ");
  }
  return "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFinding(value: unknown): value is Finding {
  return (
    isRecord(value) &&
    typeof value["code"] === "string" &&
    typeof value["message"] === "string" &&
    typeof value["severity"] === "string"
  );
}
