import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi, fetchSession, isStaleError } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function recordingFetch(response: Response | (() => Response)) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    return typeof response === "function" ? response() : response.clone();
  });
  return { fetchImpl, calls };
}

describe("api client", () => {
  it("sends the session token and JSON content type on mutations", async () => {
    const { fetchImpl, calls } = recordingFetch(
      jsonResponse(201, { id: "RE-1", notices: [], findings: [] }),
    );
    const api = createApi({ token: "tok-123", fetch: fetchImpl });

    await api.createDocument({ type: "feature", title: "Hello", tags: ["a"] });

    expect(calls).toHaveLength(1);
    const [call] = calls;
    expect(call?.url).toBe("/api/documents");
    expect(call?.init.method).toBe("POST");
    const headers = new Headers(call?.init.headers);
    expect(headers.get("X-GREGraph-Token")).toBe("tok-123");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(call?.init.body))).toEqual({
      type: "feature",
      title: "Hello",
      tags: ["a"],
    });
  });

  it("sends an empty JSON object body for DELETE and encodes every path segment", async () => {
    const { fetchImpl, calls } = recordingFetch(
      jsonResponse(200, { removed: true, notices: [] }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    await api.removeLink({ source: "A/1 x", type: "depends-on", target: "B?#" });

    const [call] = calls;
    expect(call?.url).toBe("/api/links/A%2F1%20x/depends-on/B%3F%23");
    expect(call?.init.method).toBe("DELETE");
    expect(JSON.parse(String(call?.init.body))).toEqual({});
    expect(new Headers(call?.init.headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("omits blank document filters instead of sending empty parameters", async () => {
    const { fetchImpl, calls } = recordingFetch(
      jsonResponse(200, { items: [], notices: [] }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    await api.listDocuments({ type: "", q: "  upload ", status: "" });

    expect(calls[0]?.url).toBe("/api/documents?q=upload");
    expect(calls[0]?.init.method ?? "GET").toBe("GET");
  });

  it("sends the optimistic base hash with body saves", async () => {
    const { fetchImpl, calls } = recordingFetch(
      jsonResponse(200, {
        id: "RE-1",
        body_hash: "sha256:new",
        title: "T",
        changed: true,
        findings: [],
      }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    await api.saveBody("RE-1", { text: "# T\n", base_hash: "sha256:old" });

    expect(calls[0]?.url).toBe("/api/documents/RE-1/body");
    expect(calls[0]?.init.method).toBe("PUT");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      text: "# T\n",
      base_hash: "sha256:old",
    });
  });

  it("turns the {error: Finding} envelope into an ApiError carrying the finding", async () => {
    const finding = {
      code: "E-X",
      severity: "E",
      message: "nope",
      doc_id: "RE-1",
      fix: null,
    };
    const { fetchImpl } = recordingFetch(jsonResponse(400, { error: finding }));
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api.getStatus().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, message: "nope" });
    expect((error as ApiError).finding).toEqual(finding);
    expect(isStaleError(error)).toBe(false);
  });

  it("reads FastAPI 422 detail arrays into a readable message", async () => {
    const { fetchImpl } = recordingFetch(
      jsonResponse(422, {
        detail: [{ loc: ["body", "title"], msg: "field required", type: "missing" }],
      }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api.createDocument({ type: "x", title: "", tags: [] }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toContain("field required");
    expect((error as ApiError).finding).toBeNull();
  });

  it("recognises only E-BODY-STALE 409 responses as stale-hash errors", async () => {
    const { fetchImpl } = recordingFetch(
      jsonResponse(409, {
        error: { code: "E-BODY-STALE", severity: "E", message: "changed", doc_id: "RE-1" },
      }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api
      .saveBody("RE-1", { text: "x", base_hash: "sha256:old" })
      .catch((e: unknown) => e);

    expect(isStaleError(error)).toBe(true);
  });

  it("does not treat other 409 refusals as stale", async () => {
    const { fetchImpl } = recordingFetch(
      jsonResponse(409, {
        error: { code: "E-BODY-MISSING", severity: "E", message: "gone", doc_id: "RE-1" },
      }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api
      .saveBody("RE-1", { text: "x", base_hash: "sha256:old" })
      .catch((e: unknown) => e);

    expect(isStaleError(error)).toBe(false);
    expect((error as ApiError).finding?.code).toBe("E-BODY-MISSING");
  });

  it("reports network failures as ApiError with status 0", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api.getGraph().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toMatch(/network/i);
  });

  it("handles non-JSON error bodies without throwing a parse error", async () => {
    const { fetchImpl } = recordingFetch(
      () => new Response("<html>boom</html>", { status: 500 }),
    );
    const api = createApi({ token: "t", fetch: fetchImpl });

    const error = await api.getValidation().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(500);
    expect((error as ApiError).message).toMatch(/500/);
  });
});

describe("session", () => {
  it("reads the session without a token, and the GET carries no token header", async () => {
    const { fetchImpl, calls } = recordingFetch(
      jsonResponse(200, { repository: { name: "r", git: true, degraded: false }, types: [], link_types: [], version: "0.1.0", csrf_token: "x" }),
    );

    const session = await fetchSession(fetchImpl);

    expect(session.repository.name).toBe("r");
    expect(calls[0]?.url).toBe("/api/session");
    expect(new Headers(calls[0]?.init.headers).get("X-GREGraph-Token")).toBeNull();
  });
});
