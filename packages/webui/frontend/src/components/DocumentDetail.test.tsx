import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocumentDetail } from "./DocumentDetail";
import { ApiError } from "../api/client";
import { docA, docB, makeApi, summaries } from "../test/fixtures";
import type { DocumentDetail as DocumentDetailData, SaveBodyResponse } from "../api/types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderDetail(doc: DocumentDetailData = docA, overrides: Parameters<typeof makeApi>[0] = {}) {
  const api = makeApi(overrides);
  const onSelect = vi.fn();
  const onChanged = vi.fn();
  const onDirtyChange = vi.fn();
  const utils = render(
    <DocumentDetail
      doc={doc}
      api={api}
      linkTypes={["refines", "depends-on", "verifies"]}
      documents={summaries}
      onSelect={onSelect}
      onChanged={onChanged}
      onDirtyChange={onDirtyChange}
    />,
  );
  return { api, onSelect, onChanged, onDirtyChange, ...utils };
}

describe("DocumentDetail body", () => {
  it("renders the raw markdown body as escaped text, never as markup", () => {
    const hostile = { ...docA, body_text: "<img src=x onerror=alert(1)>\n<script>bad()</script>\n# X" };
    const { container } = renderDetail(hostile);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/onerror=alert\(1\)/)).toBeInTheDocument();
  });

  it("saves with the optimistic base hash and explains the pending sync flow", async () => {
    const { api, onChanged } = renderDetail();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "# Upload documents\n\nEdited" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));

    expect(api.saveBody).toHaveBeenCalledWith("RE-FEAT-AAAAAA", {
      text: "# Upload documents\n\nEdited",
      base_hash: "sha256:aaa",
    });
    expect(onChanged).toHaveBeenCalled();
    expect(
      await screen.findByText(/pending until .*gregraph sync.*pre-commit hook/i),
    ).toBeInTheDocument();
  });

  it("disables the body editor while a save is in flight so typed text cannot be lost", async () => {
    const pending = deferred<SaveBodyResponse>();
    const { api } = renderDetail(docA, { saveBody: vi.fn(() => pending.promise) });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "saved text" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));

    const textarea = screen.getByLabelText("Markdown body");
    expect(textarea).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.type(textarea, "late keystrokes");
    expect(textarea).toHaveValue("saved text");

    pending.resolve({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] });
    await waitFor(() => expect(screen.queryByLabelText("Markdown body")).toBeNull());
    expect(api.saveBody).toHaveBeenCalledWith("RE-FEAT-AAAAAA", { text: "saved text", base_hash: "sha256:aaa" });
  });

  it("re-enables the editor with the draft intact when a save fails", async () => {
    const pending = deferred<never>();
    renderDetail(docA, { saveBody: vi.fn(() => pending.promise) });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "keep" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));
    pending.reject(new ApiError(422, "Body is invalid.", { code: "E-X", severity: "E", message: "Body is invalid." }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Body is invalid.");
    expect(screen.getByLabelText("Markdown body")).toBeEnabled();
    expect(screen.getByLabelText("Markdown body")).toHaveValue("keep");
  });

  it("cancel discards the draft without calling the API", async () => {
    const { api } = renderDetail();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "draft" } });
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Markdown body")).toBeNull();
    expect(screen.getByText(/Original body A/)).toBeInTheDocument();
    expect(api.saveBody).not.toHaveBeenCalled();
  });

  it("on a 409 stale error keeps the draft, never resubmits the old hash, and offers an explicit reload", async () => {
    const { api } = renderDetail(docA, {
      saveBody: vi.fn(async () => {
        throw new ApiError(409, "Document changed on disk.", {
          code: "E-BODY-STALE",
          severity: "E",
          message: "Document changed on disk.",
        });
      }),
      getDocument: vi.fn(async () => ({
        ...docA,
        body_text: "# Upload documents\n\nServer version",
        body_hash: "sha256:server",
      })),
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "my careful draft" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/changed/i);
    expect(api.saveBody).toHaveBeenCalledTimes(1);
    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", {
      text: "my careful draft",
      base_hash: "sha256:aaa",
    });
    expect(screen.getByLabelText("Markdown body")).toHaveValue("my careful draft");

    await user.click(screen.getByRole("button", { name: "Reload latest version" }));

    expect(api.getDocument).toHaveBeenCalledWith("RE-FEAT-AAAAAA");
    expect(screen.getByLabelText("Markdown body")).toHaveValue("my careful draft");
    expect(await screen.findByText(/Server version/)).toBeInTheDocument();
    expect(api.saveBody).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Save body" }));
    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", {
      text: "my careful draft",
      base_hash: "sha256:server",
    });
  });

  it("keeps a non-stale 409 refusal as a normal alert: draft kept, retry allowed, no reload offer", async () => {
    const saveBody = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(409, "Body is missing.", { code: "E-BODY-MISSING", severity: "E", message: "Body is missing." }),
      )
      .mockResolvedValueOnce({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] });
    const { api, onChanged } = renderDetail(docA, { saveBody });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "keep me" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Body is missing.");
    expect(screen.queryByRole("button", { name: "Reload latest version" })).toBeNull();
    expect(screen.queryByText(/changed since you started editing/)).toBeNull();
    expect(screen.getByLabelText("Markdown body")).toHaveValue("keep me");

    await user.click(screen.getByRole("button", { name: "Save body" }));

    expect(api.saveBody).toHaveBeenCalledTimes(2);
    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", { text: "keep me", base_hash: "sha256:aaa" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows other API failures without discarding the draft", async () => {
    const { api } = renderDetail(docA, {
      saveBody: vi.fn(async () => {
        throw new ApiError(422, "Body is invalid.", { code: "E-X", severity: "E", message: "Body is invalid." });
      }),
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "kept" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Body is invalid.");
    expect(screen.getByLabelText("Markdown body")).toHaveValue("kept");
    expect(api.saveBody).toHaveBeenCalledTimes(1);
  });

  it("never applies an edit draft to a different document when the selection changes", async () => {
    const { api, rerender } = renderDetail();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "draft for A" } });

    rerender(
      <DocumentDetail
        doc={docB}
        api={api}
        linkTypes={["refines"]}
        documents={summaries}
        onSelect={vi.fn()}
        onChanged={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("Markdown body")).toBeNull();
    expect(screen.getByRole("heading", { name: "Self-service" })).toBeInTheDocument();
    expect(api.saveBody).not.toHaveBeenCalled();
  });
});

describe("DocumentDetail snapshot after a successful save", () => {
  function element(doc: DocumentDetailData, api: ReturnType<typeof makeApi>) {
    return (
      <DocumentDetail
        doc={doc}
        api={api}
        linkTypes={["refines"]}
        documents={summaries}
        onSelect={vi.fn()}
        onChanged={vi.fn()}
        onDirtyChange={vi.fn()}
      />
    );
  }

  it("editing again right after a save starts from the saved text and the new hash, even before the parent refetches", async () => {
    const saveBody = vi
      .fn()
      .mockResolvedValueOnce({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] })
      .mockResolvedValueOnce({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:newer", title: "T", changed: true, findings: [] });
    const { api } = renderDetail(docA, { saveBody });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "# Upload documents\r\n\r\nSaved line" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));
    await waitFor(() => expect(screen.queryByLabelText("Markdown body")).toBeNull());

    // The parent still holds the old docA props: no refetch has happened.
    expect(screen.getByLabelText("Body text")).toHaveTextContent("Saved line");
    expect(screen.queryByText(/Original body A/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    expect(screen.getByLabelText("Markdown body")).toHaveValue("# Upload documents\n\nSaved line");
    await user.click(screen.getByRole("button", { name: "Save body" }));

    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", {
      text: "# Upload documents\n\nSaved line",
      base_hash: "sha256:new",
    });
    expect(await screen.findByRole("status")).toHaveTextContent(/pending/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  // Core update_body (spec 21.5) only converts CRLF and CR to LF. Everything else is kept as typed.
  it.each([
    ["no final newline", "# T\nbody", "# T\nbody"],
    ["multiple trailing blank lines", "# T\n\nbody\n\n\n", "# T\n\nbody\n\n\n"],
    ["empty text", "", ""],
    ["Markdown hard-break trailing spaces", "# T\nline one  \nline two", "# T\nline one  \nline two"],
    ["CRLF and CR line endings", "# T\r\nA\rB\r\n", "# T\nA\nB\n"],
  ])("acknowledges a save with %s exactly as core writes it, before any refetch", async (_label, submitted, written) => {
    const saveBody = vi
      .fn()
      .mockResolvedValueOnce({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] })
      .mockResolvedValueOnce({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:newer", title: "T", changed: true, findings: [] });
    const { api } = renderDetail(docA, { saveBody });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: submitted } });
    await user.click(screen.getByRole("button", { name: "Save body" }));
    await waitFor(() => expect(screen.queryByLabelText("Markdown body")).toBeNull());

    expect(screen.getByLabelText("Body text").textContent).toBe(written);

    await user.click(screen.getByRole("button", { name: "Edit body" }));
    expect(screen.getByLabelText("Markdown body")).toHaveValue(written);
    await user.click(screen.getByRole("button", { name: "Save body" }));
    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", { text: written, base_hash: "sha256:new" });
  });

  it("a late parent re-render with the old props cannot undo the acknowledged save", async () => {
    const { api, rerender } = renderDetail(docA, {
      saveBody: vi.fn(async () => ({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] })),
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "saved now" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));
    await waitFor(() => expect(screen.queryByLabelText("Markdown body")).toBeNull());

    rerender(element({ ...docA }, api));

    expect(screen.getByLabelText("Body text")).toHaveTextContent("saved now");
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    expect(screen.getByLabelText("Markdown body")).toHaveValue("saved now");
  });

  it("fresh parent props replace the snapshot after the save", async () => {
    const { api, rerender } = renderDetail(docA, {
      saveBody: vi.fn(async () => ({ id: "RE-FEAT-AAAAAA", body_hash: "sha256:new", title: "T", changed: true, findings: [] })),
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "saved now" } });
    await user.click(screen.getByRole("button", { name: "Save body" }));
    await waitFor(() => expect(screen.queryByLabelText("Markdown body")).toBeNull());

    rerender(element({ ...docA, body_text: "server body\n", body_hash: "sha256:server" }, api));

    expect(screen.getByLabelText("Body text")).toHaveTextContent("server body");
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    await user.click(screen.getByRole("button", { name: "Save body" }));
    expect(api.saveBody).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", { text: "server body\n", base_hash: "sha256:server" });
  });

  it("a background change never replaces an active draft: saving it still uses the hash it started from", async () => {
    const saveBody = vi.fn(async () => {
      throw new ApiError(409, "changed", { code: "E-BODY-STALE", severity: "E", message: "changed" });
    });
    const { api, rerender } = renderDetail(docA, { saveBody });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "my draft" } });

    rerender(element({ ...docA, body_text: "server body\n", body_hash: "sha256:server" }, api));

    expect(screen.getByLabelText("Markdown body")).toHaveValue("my draft");
    await user.click(screen.getByRole("button", { name: "Save body" }));
    expect(api.saveBody).toHaveBeenCalledWith("RE-FEAT-AAAAAA", { text: "my draft", base_hash: "sha256:aaa" });
    expect(await screen.findByRole("button", { name: "Reload latest version" })).toBeInTheDocument();
  });
});

describe("DocumentDetail links and tags", () => {
  it("opens an outbound link target through onSelect", async () => {
    const { onSelect } = renderDetail();
    const user = userEvent.setup();

    const outbound = screen.getByRole("list", { name: "Outbound links" });
    await user.click(within(outbound).getByRole("button", { name: "RE-GOAL-BBBBBB" }));

    expect(onSelect).toHaveBeenCalledWith("RE-GOAL-BBBBBB");
  });

  it("opens an inbound source through onSelect", async () => {
    const { onSelect } = renderDetail();
    const user = userEvent.setup();

    const inbound = screen.getByRole("list", { name: "Inbound links" });
    await user.click(within(inbound).getByRole("button", { name: "RE-TEST-CCCCCC" }));

    expect(onSelect).toHaveBeenCalledWith("RE-TEST-CCCCCC");
  });

  it("removes a link with the exact source, type, and target", async () => {
    const { api, onChanged } = renderDetail();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Remove refines link to RE-GOAL-BBBBBB" }));

    expect(api.removeLink).toHaveBeenCalledWith({
      source: "RE-FEAT-AAAAAA",
      type: "refines",
      target: "RE-GOAL-BBBBBB",
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("creates a link from the current document and shows backend refusals", async () => {
    const { api, onChanged } = renderDetail(docA, {
      createLink: vi.fn(async () => {
        throw new ApiError(409, "Link would create a cycle.", { code: "E-CYCLE", severity: "E", message: "Link would create a cycle." });
      }),
    });
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText("Link type"), "depends-on");
    await user.selectOptions(screen.getByLabelText("Target document"), "RE-TEST-CCCCCC");
    await user.click(screen.getByRole("button", { name: "Add link" }));

    expect(api.createLink).toHaveBeenCalledWith({
      source: "RE-FEAT-AAAAAA",
      type: "depends-on",
      target: "RE-TEST-CCCCCC",
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Link would create a cycle.");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("adds and removes tags by sending the whole tag list", async () => {
    const { api, onChanged } = renderDetail();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("New tag"), "urgent");
    await user.click(screen.getByRole("button", { name: "Add tag" }));
    expect(api.updateTags).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", ["core", "urgent"]);

    await user.click(screen.getByRole("button", { name: "Remove tag core" }));
    expect(api.updateTags).toHaveBeenLastCalledWith("RE-FEAT-AAAAAA", []);
    expect(onChanged).toHaveBeenCalledTimes(2);
  });
});
