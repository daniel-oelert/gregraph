import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CreateDocumentDialog } from "./CreateDocumentDialog";
import { ApiError, type Api } from "../api/client";
import { makeApi, session } from "../test/fixtures";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Opener button + dialog, so focus restoration can be observed. */
function Harness({ api, onCreated }: { api: Api; onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open ? (
        <CreateDocumentDialog
          types={session.types}
          api={api}
          onClose={() => setOpen(false)}
          onCreated={(id) => {
            setOpen(false);
            onCreated(id);
          }}
        />
      ) : null}
    </>
  );
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Title"), "Valid title");
  await user.click(screen.getByRole("button", { name: "Create" }));
}

function dialog(onClose: () => void) {
  return (
    <CreateDocumentDialog
      types={session.types}
      api={makeApi()}
      onClose={onClose}
      onCreated={vi.fn()}
    />
  );
}

describe("CreateDocumentDialog focus", () => {
  it("keeps focus in the tags field when the parent re-renders with a new onClose", async () => {
    const user = userEvent.setup();
    const { rerender } = render(dialog(() => undefined));
    const tags = screen.getByLabelText("Tags");
    await user.click(tags);
    await user.type(tags, "ab");

    rerender(dialog(() => undefined));

    expect(tags).toHaveFocus();
    expect(tags).toHaveValue("ab");
  });

  it("wraps Tab from the last control to the first inside the dialog", async () => {
    const user = userEvent.setup();
    render(dialog(() => undefined));
    screen.getByRole("button", { name: "Create" }).focus();

    await user.keyboard("{Tab}");

    expect(screen.getByLabelText("Document type")).toHaveFocus();
  });

  it("wraps Shift+Tab from the first control to the last inside the dialog", async () => {
    const user = userEvent.setup();
    render(dialog(() => undefined));
    screen.getByLabelText("Document type").focus();

    await user.keyboard("{Shift>}{Tab}{/Shift}");

    expect(screen.getByRole("button", { name: "Create" })).toHaveFocus();
  });

  it("Escape calls the most recent onClose after a re-render", async () => {
    const user = userEvent.setup();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(dialog(first));
    rerender(dialog(second));

    await user.keyboard("{Escape}");

    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });
});

describe("CreateDocumentDialog while a create request is pending", () => {
  it("Escape does not dismiss the dialog, and Cancel is disabled, until the request settles", async () => {
    const pending = deferred<{ id: string; notices: string[]; findings: never[] }>();
    const onClose = vi.fn();
    const api = makeApi({ createDocument: vi.fn(() => pending.promise) });
    const user = userEvent.setup();
    render(<CreateDocumentDialog types={session.types} api={api} onClose={onClose} onCreated={vi.fn()} />);

    await fillAndSubmit(user);
    await user.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Create document" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    pending.resolve({ id: "RE-NEW001", notices: [], findings: [] });
  });

  it("ignores a second submit while the first request is pending", async () => {
    const pending = deferred<{ id: string; notices: string[]; findings: never[] }>();
    const api = makeApi({ createDocument: vi.fn(() => pending.promise) });
    const user = userEvent.setup();
    render(<CreateDocumentDialog types={session.types} api={api} onClose={vi.fn()} onCreated={vi.fn()} />);

    await fillAndSubmit(user);
    const form = screen.getByRole("dialog", { name: "Create document" }).querySelector("form") as HTMLFormElement;
    form.requestSubmit();
    form.requestSubmit();

    expect(api.createDocument).toHaveBeenCalledTimes(1);
    pending.resolve({ id: "RE-NEW001", notices: [], findings: [] });
  });

  it("a settled create closes through onCreated with the new id", async () => {
    const pending = deferred<{ id: string; notices: string[]; findings: never[] }>();
    const api = makeApi({ createDocument: vi.fn(() => pending.promise) });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<Harness api={api} onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    await fillAndSubmit(user);
    pending.resolve({ id: "RE-NEW001", notices: [], findings: [] });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull());
    expect(onCreated).toHaveBeenCalledWith("RE-NEW001");
  });

  it("a failed create clears busy, keeps the dialog, and then Escape closes and restores focus", async () => {
    const pending = deferred<never>();
    const api = makeApi({ createDocument: vi.fn(() => pending.promise) });
    const user = userEvent.setup();
    render(<Harness api={api} onCreated={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    await fillAndSubmit(user);
    pending.reject(new ApiError(400, "Title is required.", { code: "E-TITLE", severity: "E", message: "Title is required." }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Title is required.");
    expect(screen.getByRole("button", { name: "Create" })).toBeEnabled();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open" })).toHaveFocus();
  });
});
