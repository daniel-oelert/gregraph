import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocumentList, STATUS_CHOICES } from "./DocumentList";
import { session, summaries } from "../test/fixtures";

function renderList(onFiltersChange = vi.fn()) {
  render(
    <DocumentList
      items={summaries}
      notices={[]}
      loading={false}
      error={null}
      filters={{ type: "", q: "", status: "" }}
      types={session.types}
      selectedId={null}
      onFiltersChange={onFiltersChange}
      onSelect={vi.fn()}
      onCreate={vi.fn()}
    />,
  );
  return { onFiltersChange };
}

describe("DocumentList status filter", () => {
  it("offers the unknown state used when Git status is unavailable, alongside the four core states", () => {
    expect(STATUS_CHOICES).toEqual(["draft", "active", "superseded", "deprecated", "unknown"]);
    renderList();

    const options = Array.from(screen.getByLabelText("Status").querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["", "draft", "active", "superseded", "deprecated", "unknown"]);
  });

  it("sends status=unknown through onFiltersChange when selected", async () => {
    const { onFiltersChange } = renderList();
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText("Status"), "unknown");

    expect(onFiltersChange).toHaveBeenCalledWith({ type: "", q: "", status: "unknown" });
  });
});
