import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ApiError } from "./api/client";
import type { DocumentDetail, GraphResponse } from "./api/types";
import { docA, docB, graph, makeApi, session, status, validation } from "./test/fixtures";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("App shell", () => {
  it("shows the local workspace label, navigation, and status cards", async () => {
    const api = makeApi();
    render(<App session={session} api={api} />);

    expect(screen.getByText("GREGraph")).toBeInTheDocument();
    expect(screen.getByText(/Local workspace/)).toHaveTextContent("demo-repo");
    for (const name of ["Documents", "Graph", "Validation"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    const cards = await screen.findByRole("region", { name: "Status summary" });
    expect(within(cards).getByText("draft")).toBeInTheDocument();
    expect(within(cards).getByText("active")).toBeInTheDocument();
    expect(within(cards).getByRole("button", { name: "RE-GOAL-BBBBBB refines RE-FEAT-AAAAAA" })).toBeInTheDocument();
    expect(status.counts.active).toBe(2);
  });

  it("shows a load error with an alert instead of an empty list", async () => {
    const api = makeApi({
      listDocuments: vi.fn(async () => {
        throw new ApiError(0, "Network error: the local GREGraph server is not reachable.");
      }),
    });
    render(<App session={session} api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/not reachable/);
  });

  it("shows an empty state when no documents match the filters", async () => {
    const api = makeApi({ listDocuments: vi.fn(async () => ({ items: [], notices: [] })) });
    render(<App session={session} api={api} />);

    expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
  });
});

describe("App status labels", () => {
  it("opens the source document of a pending link label", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: "RE-GOAL-BBBBBB refines RE-FEAT-AAAAAA" }));

    expect(api.getDocument).toHaveBeenLastCalledWith("RE-GOAL-BBBBBB");
    expect(await screen.findByRole("heading", { name: "Self-service" })).toBeInTheDocument();
  });
});

describe("App documents", () => {
  it("sends only the non-blank filters and refetches the list when the type changes", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await screen.findByRole("button", { name: /Upload documents/ });

    await user.selectOptions(screen.getByLabelText("Type"), "feature");
    await user.type(screen.getByLabelText("Search documents"), "upload");

    await waitFor(() =>
      expect(api.listDocuments).toHaveBeenLastCalledWith({ type: "feature", q: "upload", status: "" }),
    );
  });

  it("loads the selected document detail with inbound and outbound links", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));

    expect(await screen.findByRole("heading", { name: "Upload documents" })).toBeInTheDocument();
    expect(api.getDocument).toHaveBeenCalledWith("RE-FEAT-AAAAAA");
    expect(screen.getByRole("list", { name: "Outbound links" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Inbound links" })).toBeInTheDocument();
  });

  it("never shows a late response for a document that is no longer selected", async () => {
    const slowA = deferred<DocumentDetail>();
    const api = makeApi({
      getDocument: vi.fn((id: string) => (id === docA.id ? slowA.promise : Promise.resolve(docB))),
    });
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    await user.click(await screen.findByRole("button", { name: /Self-service/ }));
    expect(await screen.findByRole("heading", { name: "Self-service" })).toBeInTheDocument();

    slowA.resolve(docA);
    await Promise.resolve();

    expect(screen.getByRole("heading", { name: "Self-service" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload documents" })).toBeNull();
  });

  it("asks before abandoning an unsaved draft and stays put when declined", async () => {
    const api = makeApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    await screen.findByRole("heading", { name: "Upload documents" });
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "unsaved" } });

    await user.click(screen.getByRole("button", { name: /Self-service/ }));

    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("Markdown body")).toHaveValue("unsaved");
    expect(api.getDocument).not.toHaveBeenCalledWith("RE-GOAL-BBBBBB");
  });

  it("refetches the list, status, validation, and graph after a mutation", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    await screen.findByRole("heading", { name: "Upload documents" });
    const listCalls = vi.mocked(api.listDocuments).mock.calls.length;
    const statusCalls = vi.mocked(api.getStatus).mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Remove refines link to RE-GOAL-BBBBBB" }));

    await waitFor(() => expect(vi.mocked(api.listDocuments).mock.calls.length).toBeGreaterThan(listCalls));
    expect(vi.mocked(api.getStatus).mock.calls.length).toBeGreaterThan(statusCalls);
    expect(api.getValidation).toHaveBeenCalled();
  });
});

describe("App New document and unsaved drafts", () => {
  async function dirtyDocumentA(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    await screen.findByRole("heading", { name: "Upload documents" });
    await user.click(screen.getByRole("button", { name: "Edit body" }));
    fireEvent.change(screen.getByLabelText("Markdown body"), { target: { value: "unsaved" } });
  }

  it("asks before opening the create dialog; declining keeps the draft and the dialog closed", async () => {
    const api = makeApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await dirtyDocumentA(user);

    await user.click(screen.getByRole("button", { name: "New document" }));

    expect(confirm).toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull();
    expect(screen.getByLabelText("Markdown body")).toHaveValue("unsaved");
  });

  it("opens the create dialog after the user accepts discarding the draft", async () => {
    const api = makeApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await dirtyDocumentA(user);

    await user.click(screen.getByRole("button", { name: "New document" }));

    expect(confirm).toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Create document" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Markdown body")).toBeNull();
    expect(screen.getByText(/Original body A/)).toBeInTheDocument();
  });

  it("makes the page behind the create dialog inert while it is open", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    const heading = await screen.findByRole("heading", { name: "Upload documents" });
    expect(heading.closest("[inert]")).toBeNull();

    await user.click(screen.getByRole("button", { name: "New document" }));

    expect(screen.getByRole("dialog", { name: "Create document" })).toBeInTheDocument();
    expect(heading.closest("[inert]")).not.toBeNull();
    expect(screen.getByRole("dialog", { name: "Create document" }).closest("[inert]")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(heading.closest("[inert]")).toBeNull();
  });
});

describe("App create request in flight", () => {
  it("keeps the background inert and the dialog open while the create is pending; Escape does not discard", async () => {
    const pending = deferred<{ id: string; notices: string[]; findings: never[] }>();
    const api = makeApi({
      createDocument: vi.fn(() => pending.promise),
      getDocument: vi.fn(async (id: string) =>
        id === "RE-FEAT-NEW001" ? { ...docA, id, title: "New thing", body_text: "# New thing" } : docA,
      ),
    });
    const user = userEvent.setup();
    render(<App session={session} api={api} />);
    await user.click(await screen.findByRole("button", { name: /Upload documents/ }));
    const heading = await screen.findByRole("heading", { name: "Upload documents" });

    await user.click(screen.getByRole("button", { name: "New document" }));
    const dialog = screen.getByRole("dialog", { name: "Create document" });
    await user.type(within(dialog).getByLabelText("Title"), "New thing");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    await user.keyboard("{Escape}");

    expect(screen.getByRole("dialog", { name: "Create document" })).toBeInTheDocument();
    expect(heading.closest("[inert]")).not.toBeNull();

    pending.resolve({ id: "RE-FEAT-NEW001", notices: [], findings: [] });

    expect(await screen.findByRole("heading", { name: "New thing" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull();
    expect(screen.getByRole("heading", { name: "New thing" }).closest("[inert]")).toBeNull();
  });
});

describe("App create dialog", () => {
  it("omits the system cr type, creates a document, and selects it", async () => {
    const api = makeApi({
      listDocuments: vi.fn(async () => ({ items: [], notices: [] })),
      getDocument: vi.fn(async () => ({ ...docA, id: "RE-FEAT-NEW001", title: "New thing", body_text: "# New thing" })),
    });
    const user = userEvent.setup();
    render(<App session={{ ...session, types: [...session.types, { name: "cr", kind: "system" }] }} api={api} />);

    await user.click(await screen.findByRole("button", { name: "New document" }));
    const dialog = screen.getByRole("dialog", { name: "Create document" });
    const typeSelect = within(dialog).getByLabelText("Document type");
    expect(within(typeSelect).queryByRole("option", { name: "cr" })).toBeNull();
    await user.selectOptions(typeSelect, "feature");
    await user.type(within(dialog).getByLabelText("Title"), "New thing");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(api.createDocument).toHaveBeenCalledWith({ type: "feature", title: "New thing", tags: [] });
    expect(await screen.findByRole("heading", { name: "New thing" })).toBeInTheDocument();
    expect(api.getDocument).toHaveBeenCalledWith("RE-FEAT-NEW001");
    expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull();
  });

  it("keeps the dialog open with the backend error when creation fails", async () => {
    const api = makeApi({
      createDocument: vi.fn(async () => {
        throw new ApiError(400, "Title is required.", { code: "E-TITLE", severity: "E", message: "Title is required." });
      }),
    });
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: "New document" }));
    const dialog = screen.getByRole("dialog", { name: "Create document" });
    await user.type(within(dialog).getByLabelText("Title"), "x");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Title is required.");
    expect(screen.getByRole("dialog", { name: "Create document" })).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(await screen.findByRole("button", { name: "New document" }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull();
  });
});

describe("App graph and validation", () => {
  it("opens a document from a keyboard-focusable graph node", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(screen.getByRole("button", { name: "Graph" }));
    const node = await screen.findByRole("button", { name: /RE-GOAL-BBBBBB.*Self-service/ });
    node.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: "Self-service" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Documents" })).toHaveAttribute("aria-current", "page");
  });

  it("shows a truncation notice when the graph is truncated and still draws its nodes", async () => {
    const truncated: GraphResponse = { ...graph, truncated: true };
    const api = makeApi({ getGraph: vi.fn(async () => truncated) });
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(screen.getByRole("button", { name: "Graph" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/truncated.*300/i);
    expect(screen.getByRole("button", { name: /RE-FEAT-AAAAAA/ })).toBeInTheDocument();
  });

  it("selects the document behind a validation finding", async () => {
    const api = makeApi();
    const user = userEvent.setup();
    render(<App session={session} api={api} />);

    await user.click(screen.getByRole("button", { name: "Validation" }));
    await user.click(await screen.findByRole("button", { name: "Open RE-GOAL-BBBBBB" }));

    expect(screen.getByRole("button", { name: "Documents" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "Self-service" })).toBeInTheDocument();
    expect(validation.warning_count).toBe(1);
  });
});
